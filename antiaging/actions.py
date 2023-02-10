import datetime
import time

from chaosk8s import create_k8s_api_client
from chaoslib.exceptions import ActivityFailed
from chaoslib.types import Secrets
from kubernetes import client
from kubernetes.client import CoreV1Api
from kubernetes.client import V1Node
from kubernetes.client import V1Pod
from kubernetes.client.rest import ApiException
from logzero import logger
from pytz import UTC


__all__ = ["nodes_older_than"]


def get_k8s_client(secrets) -> CoreV1Api:
    return client.CoreV1Api(create_k8s_api_client(secrets))


def nodes_older_than(
    days: int,
    hours: int = 0,
    secrets: Secrets = None,
    count: int = 1,
    dry_run: bool = False,
    eviction_timeout_seconds: int = 300,
    node_delete_timeout_seconds: int = 180,
) -> dict[str, dict]:  # returns a map that shows the nodes and the amount of pods that are scheduled there
    if dry_run:
        logger.info("Running in dry run mode")

    k8s = get_k8s_client(secrets)
    all_nodes = k8s.list_node().items
    candidates = []
    max_age = datetime.datetime.now(UTC) - datetime.timedelta(days=days, hours=hours)
    logger.info(f"Collecting nodes that are older than {max_age} ({days}d {hours}h) for drainage and deletion")
    result = {}

    for node in all_nodes:
        if node.metadata.creation_timestamp <= max_age:
            candidates.append(node)

    if not candidates:
        logger.info("No candidates found, aborting")
        return {}

    # the first element is going to be the oldest candidate -> that means the last element is the youngest candidate
    candidates.sort(key=lambda x: x.metadata.creation_timestamp)

    logger.info(
        f"Found {len(candidates)} candidates: [{', '.join(f'{candidate.metadata.name} {candidate.metadata.creation_timestamp}' for candidate in candidates)}]"
    )
    candidates = candidates[: min(count, len(candidates))]

    evictable_pods = []

    for node in candidates:
        node_name = node.metadata.name
        result[node_name] = {"creation_timestamp": node.metadata.creation_timestamp}
        pods = k8s.list_pod_for_all_namespaces(field_selector=f"spec.nodeName={node_name}")
        logger.debug(f"Found {len(pods.items)} pods on node '{node_name}'")

        cordon_node(k8s, node, dry_run)
        evictable_node_pods, non_evictable_pods = get_pods_from_node(k8s, node)
        result[node_name]["evictable_pods"] = [pod.metadata.name for pod in evictable_node_pods]
        result[node_name]["non_evictable_pods"] = [pod.metadata.name for pod in non_evictable_pods]

        logger.info(f"Found {len(evictable_pods)} pods on node {node_name} that have to be evicted")

        if not evictable_node_pods:
            logger.info(f"No pods to evict on node {node_name}")

        for pod in evictable_node_pods:
            evict_pod(k8s, pod, dry_run)

        wait_for_pods_to_evict(k8s, evictable_node_pods, eviction_timeout_seconds, dry_run)

        delete_node(k8s, node, node_delete_timeout_seconds, dry_run)
    return result


def delete_node(k8s: CoreV1Api, node: V1Node, delete_timeout: int = 60, dry_run=False):
    body = client.V1DeleteOptions()

    if not dry_run:
        res = k8s.delete_node(node.metadata.name, body=body, grace_period_seconds=delete_timeout)

        if res.status != "Success":
            logger.debug(f"Terminating node failed: {res.message}")
    else:
        logger.debug(f"Would've deleted node {node.metadata.name} (dry run) ")


def wait_for_pods_to_evict(k8s: CoreV1Api, pods: list[V1Pod], timeout: int, dry_run: bool = False):
    logger.info(f"Waiting for {len(pods)} to be evicted")
    start_time = time.time()

    evictable_pods = pods[:]
    while True:
        pending_pods = evictable_pods[:]
        if time.time() - start_time > timeout:
            logger.info(f"Eviction for {len(pods)} pods took too long. {len(pending_pods)} pods are missing")
            remaining_pods = "\n".join([p.metadata.name for p in pending_pods])
            raise ActivityFailed(
                f"Draining nodes did not completed within {timeout}s. " f"Remaining pods are:\n{remaining_pods}"
            )

        for pod in evictable_pods:
            try:
                p = k8s.read_namespaced_pod(pod.metadata.name, pod.metadata.namespace)
                # rescheduled elsewhere?
                if p.metadata.uid != pod.metadata.uid:
                    pending_pods.remove(pod)
                    continue
                logger.debug(f"Pod '{p.metadata.name}' still around in phase: {p.status.phase}")
            except ApiException as x:
                if x.status == 404:
                    # pod is gone...
                    pending_pods.remove(pod)
        evictable_pods = pending_pods[:]

        if not evictable_pods:
            logger.info(f"All {len(pods)} pods evicted")
            break

        time.sleep(5)
        if dry_run:
            logger.info("Not waiting for pods to be evicted (dry run)")
            break


def get_pods_from_node(k8s: CoreV1Api, node: V1Node) -> (list[V1Pod], list[V1Pod]):
    pods = k8s.list_pod_for_all_namespaces(field_selector=f"spec.nodeName={node.metadata.name}")

    evictable_pods = []
    non_evictable_pods = []
    for pod in pods.items:
        annotations = pod.metadata.annotations
        phase = pod.status.phase

        if annotations and "kubernetes.io/config.mirror" in annotations:
            non_evictable_pods.append(pod)
            continue

        if phase in ["Succeeded", "Failed"]:
            logger.debug(f"Pod {pod.metadata.name} on node {node.metadata.name} is in phase {phase}")
            evictable_pods.append(pod)
            continue

        if pod.metadata.owner_references:
            for owner in pod.metadata.owner_references:
                if owner.controller and owner.kind != "DaemonSet":
                    evictable_pods.append(pod)
                    break
                elif owner.kind == "DaemonSet":
                    non_evictable_pods.append(pod)
                    logger.debug(
                        f"Pod '{pod.metadata.name}' on node '{node.metadata.name}' is owned by a DaemonSet."
                        " Will not evict it"
                    )
                    break
            else:
                raise ActivityFailed(
                    f"Pod '{pod.metadata.name}' on node '{node.metadata.name}' is unmanaged, cannot drain"
                    " this node. Delete it manually first?"
                )
        else:
            logger.debug(f"Pod {pod.metadata.name} has no owner")
            evictable_pods.append(pod)
    return evictable_pods, non_evictable_pods


def cordon_node(k8s: CoreV1Api, node: V1Node, dry_run=False) -> None:
    """
    Cordon nodes will mark the node so that new pods cannot get scheduled
    """
    body = {"spec": {"unschedulable": True}}

    try:
        if not dry_run:
            k8s.patch_node(node.metadata.name, body)
        else:
            logger.info(f"Would have marked node {node.metadata.name} as unscheduleable")
    except ApiException as x:
        logger.info(f"Unscheduling node '{node.metadata.name}' failed: {x.body}")
        raise ActivityFailed(f"Failed to unschedule node '{node.metadata.name}': {x.body}")


def evict_pod(k8s: CoreV1Api, pod: V1Pod, dry_run=False) -> None:
    eviction = client.V1Eviction()
    eviction.metadata = client.V1ObjectMeta()
    eviction.metadata.name = pod.metadata.name
    eviction.metadata.namespace = pod.metadata.namespace
    eviction.delete_options = client.V1DeleteOptions()

    try:
        if not dry_run:
            k8s.create_namespaced_pod_eviction(pod.metadata.name, pod.metadata.namespace, body=eviction)
        else:
            logger.info(f"Would evict pod {pod.metadata.name} (dry run)")
    except ApiException as x:
        raise ActivityFailed(f"Failed to evict pod {pod.metadata.name}: {x.body}")
