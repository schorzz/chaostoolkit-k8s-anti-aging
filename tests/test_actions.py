import datetime

import pytest
import pytz
from kubernetes.client import V1Node
from kubernetes.client import V1Pod

import antiaging
from antiaging.actions import cordon_node
from antiaging.actions import delete_node
from antiaging.actions import evict_pod
from antiaging.actions import get_pods_from_node
from antiaging.actions import nodes_older_than
from antiaging.actions import wait_for_pods_to_evict
from tests.conftest import CoreV1TestApi


def test_delete_node(k8s_client: CoreV1TestApi, nodes: list[V1Node]):
    assert len(nodes) > 0
    nodes_in_cluster = len(k8s_client.list_node().items)
    assert nodes_in_cluster == len(nodes)
    delete_node(k8s_client, nodes[0])
    assert nodes_in_cluster - 1 == len(k8s_client.list_node().items), "Cluster doesn't have one node less"
    assert nodes[0] not in k8s_client.list_node().items


@pytest.mark.timeout(10)
def test_wait_for_pod_eviction(k8s_client: CoreV1TestApi, faker):
    def reschedule_pod():
        for pod in k8s_client.pods:
            pod.metadata.uid += "-1"
            pod.metadata.name = faker.name()

    with k8s_client.set_namespaced_pod_func(reschedule_pod):
        assert len(k8s_client.pods) > 0
        wait_for_pods_to_evict(k8s_client, k8s_client.pods, timeout=10)


@pytest.mark.parametrize("n_pods", [100])
def test_get_pods_from_node(k8s_client: CoreV1TestApi, pods: list[V1Pod]):
    assert len(k8s_client.nodes) > 0
    node = k8s_client.nodes[0]
    evictable_pods, non_evictable_pods = get_pods_from_node(k8s_client, node)
    node_pods = evictable_pods + non_evictable_pods
    assert len(pods) > len(node_pods) > 0
    for pod in pods:
        if pod.spec.node_name == node.metadata.name:
            assert pod in node_pods, "pod is not on node"


def test_cordon_node(k8s_client: CoreV1TestApi, nodes: list[V1Node]):
    assert len(nodes) > 0
    node = nodes[0]
    cordon_node(k8s_client, node)
    cordoned_node = k8s_client.get_node(node.metadata.name)
    assert cordoned_node.metadata.name == node.metadata.name
    assert cordoned_node.spec.unschedulable, "Node is not cordoned"


def test_evict_pod(k8s_client: CoreV1TestApi, pods: list[V1Pod]):
    assert len(pods) > 0
    pod = pods[0]

    evict_pod(k8s_client, pod)

    evicted_pod = k8s_client.read_namespaced_pod(pod.metadata.name, pod.metadata.namespace)
    assert evicted_pod.status.phase == "Succeeded"


@pytest.mark.timeout(10)
@pytest.mark.parametrize("n_nodes", [2])
def test_nodes_older_than(k8s_client: CoreV1TestApi, monkeypatch, faker):
    def get_k8s_client_mock(*args, **kwargs):
        return k8s_client

    monkeypatch.setattr(antiaging.actions, "get_k8s_client", get_k8s_client_mock)

    assert len(k8s_client.nodes) == 2
    k8s_client.nodes[0].metadata.creation_timestamp = datetime.datetime.now(tz=pytz.UTC) - datetime.timedelta(days=20)
    k8s_client.nodes[1].metadata.creation_timestamp = datetime.datetime.now(tz=pytz.UTC) - datetime.timedelta(days=5)
    assert len(k8s_client.list_node().items) == 2
    old_node_name = k8s_client.nodes[0].metadata.name

    def reschedule_pod():
        for pod in k8s_client.pods:
            pod.metadata.uid += "-1"
            pod.metadata.name = faker.name()

    with k8s_client.set_namespaced_pod_func(reschedule_pod):
        resp = nodes_older_than(days=10)
        assert k8s_client.nodes[0].metadata.name not in resp
        assert len(k8s_client.list_node().items) == 1
        assert old_node_name in resp
