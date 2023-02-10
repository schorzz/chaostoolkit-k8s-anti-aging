import contextlib
import dataclasses

import pytest
from faker import Faker
from kubernetes.client import ApiException
from kubernetes.client import V1Node
from kubernetes.client import V1NodeList
from kubernetes.client import V1NodeSpec
from kubernetes.client import V1ObjectMeta
from kubernetes.client import V1OwnerReference
from kubernetes.client import V1Pod
from kubernetes.client import V1PodList
from kubernetes.client import V1PodSpec
from kubernetes.client import V1PodStatus
from kubernetes.client.rest import RESTResponse
from pytz import UTC


@dataclasses.dataclass
class httpResponse:
    status: str
    reason: str
    data: str


class CoreV1TestApi:
    def __init__(self):
        self.nodes: list[V1Node] = []
        self.pods: list[V1Pod] = []
        self._read_namespaced_pod = None

    def clear(self):
        self.nodes = []
        self.pods = []

    def add_node(self, node: V1Node):
        self.nodes.append(node)
        assert len(self.nodes) <= 2

    def delete_node(self, name: str, **kwargs):
        node = None
        for candidate in self.nodes:
            if candidate.metadata.name == name:
                node = candidate
                break
        else:
            raise ApiException(status=404, reason=f"Node '{name}' not found")
        self.nodes.remove(node)
        return RESTResponse(httpResponse("Success", "", ""))

    @contextlib.contextmanager
    def set_namespaced_pod_func(self, func=None):
        old = self._read_namespaced_pod
        self._read_namespaced_pod = func
        yield
        self._read_namespaced_pod = old

    def read_namespaced_pod(self, name, namespace, **kwargs) -> V1Pod:
        if self._read_namespaced_pod:
            self._read_namespaced_pod()

        for candidate in self.pods:
            if candidate.metadata.namespace == namespace and candidate.metadata.name == name:
                return candidate
        raise ApiException(status=404, reason=f"Pod '{name}' not found in namespace {namespace}")

    def add_pod(self, pod: V1Pod):
        pod.status = V1PodStatus(phase="Running")
        self.pods.append(pod)

    def list_pod_for_all_namespaces(self, field_selector: str, **kwargs) -> V1PodList:
        if "spec.nodeName" not in field_selector:
            return V1PodList(items=[])
        node_selector = field_selector.split("=")
        pods = []
        for pod in self.pods:
            if pod.spec.node_name == node_selector[1]:
                pods.append(pod)
        return V1PodList(items=pods)

    def patch_node(self, name: str, body: dict, **kwargs):
        if "spec" in body and "unschedulable" in body["spec"]:
            for node in self.nodes:
                if node.metadata.name == name:
                    node.spec.unschedulable = body["spec"]["unschedulable"]
                    break

    def create_namespaced_pod_eviction(self, name: str, namespace: str, body: dict, **kwargs):
        for pod in self.pods:
            if pod.metadata.name == name and pod.metadata.namespace == namespace:
                pod.status.phase = "Succeeded"
                return

    def list_node(self) -> V1NodeList:
        return V1NodeList(items=self.nodes[:])

    def get_node(self, name: str) -> V1Node:
        for node in self.nodes:
            if node.metadata.name == name:
                return node
        raise ApiException(status=404, reason=f"Node '{name}' not found")


@pytest.fixture(params=[2])
def n_nodes(request) -> int:
    return request.param


@pytest.fixture(params=[None])
def n_pods(request, n_nodes: int) -> int:
    return request.param or n_nodes


@pytest.fixture
def nodes(n_nodes: int, faker: Faker) -> list[V1Node]:
    return [
        V1Node(
            metadata=V1ObjectMeta(
                name=faker.name(),
                creation_timestamp=faker.date_time(tzinfo=UTC),
                annotations={},
                uid=faker.name(),
            ),
            spec=V1NodeSpec(),
            api_version="v1",
        )
        for _ in range(n_nodes)
    ]


@pytest.fixture
def pods(n_pods: int, nodes: list[V1Node], faker: Faker) -> list[V1Pod]:
    pods = [
        V1Pod(
            metadata=V1ObjectMeta(
                name=faker.name(),
                namespace=faker.random_element(elements=["default", "kube_system"]),
                annotations={},
                owner_references=[
                    V1OwnerReference(
                        controller=True,
                        kind=faker.random_element(elements=["DeamonSet", "ReplicaSet"]),
                        api_version="v1",
                        name=faker.name(),
                        uid=faker.name(),
                    )
                ],
                uid=faker.name(),
            ),
            spec=V1PodSpec(containers=[]),
            status=V1PodStatus(phase=faker.random_element(elements=["Running", "Succeeded"])),
            api_version="v1",
        )
        for _ in range(n_pods)
    ]

    for i in range(len(pods)):
        node = nodes[i % len(nodes)]
        pods[i].spec.node_name = node.metadata.name
        pods[i].metadata.creation_timestamp = faker.date_time_between(start_date=node.metadata.creation_timestamp)

    return pods


@pytest.fixture
def k8s_client(nodes: list[V1Node], pods: list[V1Pod]) -> CoreV1TestApi:
    client = CoreV1TestApi()

    for node in nodes:
        client.add_node(node)

    for pod in pods:
        client.add_pod(pod)

    return client
