# 纠错历史配置
# 每条记录是一个字典，包含 "wrong"（错误文本）和 "right"（正确文本）
# 程序会通过 RAG 检索相似的历史记录，辅助 LLM 进行纠错

RECTIFICATIONS = [
    {
        "wrong": 'Do you know cloud code? It is used for writing code',
        "right": 'Do you know Claude Code? It is used for writing code',
    },
]
