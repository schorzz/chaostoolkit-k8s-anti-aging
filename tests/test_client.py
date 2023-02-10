from kubernetes.client import V1Node
from kubernetes.client import V1Pod

from tests.conftest import CoreV1TestApi


def test_node_adding_and_removal(k8s_client: CoreV1TestApi, nodes: list[V1Node]):
    k8s_client.clear()
    assert len(k8s_client.list_node().items) == 0
    k8s_client.add_node(nodes[0])
    assert len(k8s_client.list_node().items) == 1
    k8s_client.delete_node(nodes[0].metadata.name)
    assert len(k8s_client.list_node().items) == 0


def test_get_node(k8s_client: CoreV1TestApi, nodes: list[V1Node]):
    node_name = nodes[0].metadata.name
    node = k8s_client.get_node(node_name)
    assert node is not None
    assert node.metadata.name == node_name


def test_read_namespaced_pod(k8s_client: CoreV1TestApi, pods: list[V1Pod]):
    assert len(k8s_client.pods) > 0
    pod = pods[0]
    result = k8s_client.read_namespaced_pod(pod.metadata.name, pod.metadata.namespace)
    assert result.metadata.name == pod.metadata.name
