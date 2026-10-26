"""Chinese labels on actual LangGraph topology, rendered by its native API."""
from pathlib import Path
from graph import workflow, build_clarification_graph, build_document_graph, NODE_LABELS


def chinese_topology(compiled):
    topology = compiled.get_graph(xray=False)
    labels = {**NODE_LABELS, '__start__': '开始', '__end__': '结束'}
    for key, node in list(topology.nodes.items()):
        topology.nodes[key] = node._replace(name=labels.get(key, key))
    edge_labels = {'chat': '提问', 'notes': '记录笔记', 'continue': '继续补充',
                   'clarification': '沟通或笔记', 'documentation': '生成文档',
                   'save_final': '确认定稿', 'save_failure': '失败',
                   'human_review': '成功', 'await_user': '重试'}
    topology.edges = [edge._replace(data=edge_labels.get(edge.data, edge.data)) for edge in topology.edges]
    return topology


def main():
    folder = Path(__file__).resolve().parent / 'docs'
    folder.mkdir(exist_ok=True)
    for name, compiled in [('workflow-native', workflow),
                           ('clarification-native', build_clarification_graph()),
                           ('document-native', build_document_graph())]:
        graph = chinese_topology(compiled)
        (folder / (name + '.mmd')).write_text(graph.draw_mermaid(), encoding='utf-8')
        # Numeric Mermaid entities keep native API URLs ASCII-safe (raw Chinese
        # base64 can contain '/' and be interpreted as extra URL path segments).
        for key, node in list(graph.nodes.items()):
            label = ''.join(f'#{ord(c)};' if ord(c) > 127 else c for c in node.name)
            graph.nodes[key] = node._replace(name='"' + label + '"')
        png = graph.draw_mermaid_png(max_retries=2)
        (folder / (name + '.png')).write_bytes(png)
        print(folder / (name + '.png'))


if __name__ == '__main__':
    main()
