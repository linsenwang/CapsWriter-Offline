"""
Ollama 模型生命周期管理

功能：
1. 服务启动时预热/加载模型，并设置为常驻（keep_alive=-1）
2. 服务停止时卸载模型，释放 GPU 内存（keep_alive=0）

这样模型启停跟随 pm2 管理的服务进程，避免服务停止后仍占用 GPU。
"""
import logging
from ollama import Client as OllamaClient

logger = logging.getLogger('ollama_lifecycle')

# 默认配置（避免导入 util.llm 触发连锁依赖）
DEFAULT_OLLAMA_HOST = 'http://localhost:11434'
DEFAULT_OLLAMA_TIMEOUT = 20.0


class OllamaLifecycleManager:
    """Ollama 模型生命周期管理器"""

    def __init__(self):
        self._client: OllamaClient = None
        self._model: str = None

    def initialize(self, model: str, host: str = None):
        """
        初始化并加载模型

        Args:
            model: 模型名称，如 'gemma4:e4b'
            host: Ollama 服务地址，默认使用 localhost:11434
        """
        host = host or DEFAULT_OLLAMA_HOST
        timeout = DEFAULT_OLLAMA_TIMEOUT

        self._client = OllamaClient(host=host, timeout=timeout, trust_env=False)
        self._model = model

        logger.info(f"正在加载 Ollama 模型 {model}...")
        self._load()

    def _load(self):
        """发送预热请求，设置 keep_alive=-1 使模型常驻内存"""
        if not self._client or not self._model:
            return

        try:
            # 空 prompt 的 generate 请求用于加载模型
            self._client.generate(
                model=self._model,
                prompt='',
                keep_alive=-1,  # -1 表示永久保持，覆盖默认的 5 分钟
                options={'temperature': 0},
            )
            logger.info(f"Ollama 模型 {self._model} 已加载并设置为常驻")
        except Exception as e:
            logger.error(f"Ollama 模型 {self._model} 加载失败: {e}")

    def unload(self):
        """卸载模型，keep_alive=0 立即释放 GPU 内存"""
        if not self._client or not self._model:
            return

        try:
            self._client.generate(
                model=self._model,
                prompt='',
                keep_alive=0,  # 0 表示立即卸载
                options={'temperature': 0},
            )
            logger.info(f"Ollama 模型 {self._model} 已卸载，GPU 内存已释放")
        except Exception as e:
            logger.error(f"Ollama 模型 {self._model} 卸载失败: {e}")


# 全局单例
ollama_lifecycle = OllamaLifecycleManager()
