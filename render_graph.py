"""Export the actual cyclic graph with LangGraph's native renderer."""
from pathlib import Path
from graph import NODE_LABELS, WorkflowState, workflow
from render_native_graph import main as render_png, chinese_topology


def main():
    render_png()
    folder = Path(__file__).resolve().parent / 'docs'
    mermaid = chinese_topology(workflow).draw_mermaid()
    (folder / 'workflow.mmd').write_text(mermaid, encoding='utf-8')
    lines = ['# 当前 LangGraph 工作流', '', '![中文主图](workflow-native.png)', '', '## 需求澄清子图', '', '![需求澄清](clarification-native.png)', '', '## 文档生成子图', '', '![文档生成](document-native.png)', '',
             '由实际编译图生成。等待输入和人工审阅使用 interrupt；每次请求用同一 session ID 恢复 SQLite checkpoint。', '',
             '```mermaid', mermaid, '```', '', '## 主图与子图节点', '', '| 节点 | 职责 |', '| --- | --- |']
    lines += [f'| `{key}` | {label} |' for key, label in NODE_LABELS.items()]
    lines += ['', '## 状态字段', '', ', '.join(WorkflowState.__annotations__), '',
              '需求方与总结是模型节点；记录、校验、文档渲染和保存是确定性节点，同属 Agent 工作流。',
              '总结只读取实际对话、个人笔记及公开开场，不读取需求方隐藏设定。文档保存证据快照和 Markdown。',
              '模型失败走 save_failure，保留已记录的问题；相同请求重试不重复追加问题。',
              '定稿后图结束；继续补充会从已有会话开启下一次流程，旧文档与来源快照保留。',
              '会话锁适用于单进程部署。图节点负责会话写入，checkpointer 负责节点恢复；密钥不进入两者。', '']
    (folder / 'workflow.md').write_text('\n'.join(lines), encoding='utf-8')
    # Old hand-laid DAG SVG is invalid for the new cyclic graph.
    (folder / 'workflow.svg').unlink(missing_ok=True)


if __name__ == '__main__':
    main()
