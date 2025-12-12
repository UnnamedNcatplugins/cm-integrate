from ncatbot.plugin_system import NcatBotPlugin, command_registry
from dataclasses import dataclass, field
from .config_proxy import ProxiedPluginConfig
from ncatbot.utils import get_log
from ncatbot.core.event import GroupMessageEvent

PLUGIN_NAME = 'UnnamedCmIntegrate'

logger = get_log(PLUGIN_NAME)


@dataclass
class CmConfig(ProxiedPluginConfig):
    base_url: str = field(default='')


class UnnamedCmIntegrate(NcatBotPlugin):
    name = PLUGIN_NAME  # 必须，插件名称，要求全局独立
    version = "0.0.1"  # 必须，插件版本
    dependencies = {}  # 必须，依赖的其他插件和版本
    description = "集成色孽神选"  # 可选
    author = "default_user"  # 可选

    async def on_load(self) -> None:
        await super().on_load()

    async def on_close(self) -> None:
        await super().on_close()
