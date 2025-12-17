from httpx import HTTPStatusError
from ncatbot.plugin_system import NcatBotPlugin, command_registry, filter_registry, admin_filter
from dataclasses import dataclass, field
from .config_proxy import ProxiedPluginConfig
from ncatbot.utils import get_log
from ncatbot.core.event import GroupMessageEvent, BaseMessageEvent
import httpx
from typing import Optional
import re

PLUGIN_NAME = 'UnnamedCmIntegrate'

logger = get_log(PLUGIN_NAME)
GROUP_FILTER_NAME = '__unnamed_cm_group_filter__'


@filter_registry.register(GROUP_FILTER_NAME)
def filter_group_by_config(event: BaseMessageEvent) -> bool:
    if not event.is_group_event():
        return False
    assert isinstance(event, GroupMessageEvent)
    if global_plugin_instance is None:
        raise RuntimeError(f"无法获取到插件实例, 你是不是直接引用了这个文件")
    if not global_plugin_instance.cm_config.enable_group_filter:
        return True
    return int(event.group_id) in global_plugin_instance.cm_config.filter_group


@dataclass
class CmConfig(ProxiedPluginConfig):
    auth_token: str = field(default='')
    base_url: str = field(default='')
    enable_group_filter: bool = field(default=False)
    filter_group: list[int] = field(default_factory=list)


def extract_hitomi_id(hitomi_url: str) -> Optional[str]:
    __match = re.search(r'(\d+)\.html$', hitomi_url)
    if __match:
        return __match.group(1)
    return None


class UnnamedCmIntegrate(NcatBotPlugin):
    name = PLUGIN_NAME  # 必须，插件名称，要求全局独立
    version = "0.0.1"  # 必须，插件版本
    dependencies = {}  # 必须，依赖的其他插件和版本
    description = "集成色孽神选"  # 可选
    author = "default_user"  # 可选

    cm_config: Optional[CmConfig] = None
    init = False

    async def on_load(self) -> None:
        self.cm_config = CmConfig(self)
        global global_plugin_instance
        global_plugin_instance = self
        if not self.cm_config.base_url or not self.cm_config.auth_token:
            logger.error(f'未配置后端url或auth token, 神选集成将禁用')
            return
        logger.info(f'测试色孽神选后端连通性')
        link_ok = False
        async with httpx.AsyncClient(base_url=self.cm_config.base_url,
                                     cookies={'password': self.cm_config.auth_token}) as client:
            try:
                resp = await client.get('/download_status')
                if resp.status_code == 200:
                    link_ok = True
                else:
                    logger.error(f'测试链接返回{resp.status_code}')
            except Exception as e:
                logger.exception(f'请求失败', exc_info=e)
        if not link_ok:
            logger.error(f'连通性测试失败, 将禁用神选集成')
            return
        self.init = True
        await super().on_load()

    @admin_filter
    @filter_registry.filters(GROUP_FILTER_NAME)
    @command_registry.command('cm')
    async def log_comic(self, event: GroupMessageEvent, hitomi_input: str):
        if not self.init:
            await event.reply(f'神选集成未激活, 具体原因看log')
            return
        try:
            hitomi_id = int(hitomi_input)
        except ValueError:
            hitomi_id = extract_hitomi_id(hitomi_input)
        if not hitomi_id:
            await event.reply(f'不是hitomi id也不是url, 你发了一坨')
            return
        try:
            async with httpx.AsyncClient(base_url=self.cm_config.base_url,
                                         cookies={'password': self.cm_config.auth_token}) as client:
                resp = await client.get(f'/get_document/{hitomi_id}')
                if resp.status_code == 307:
                    location = resp.headers.get('Location')
                    await event.reply(f'本子已存在, 访问以下网址\n{self.cm_config.base_url}{location}')
                    return
                if resp.status_code != 404:
                    resp.raise_for_status()
                if resp.status_code < 300:
                    return
                resp = await client.get(f'/comic/get_missing_tags?source_document_id={hitomi_id}&source_id=1')
                missing_tags = resp.json()
                if missing_tags:
                    redirect_url = f'{self.cm_config.base_url}/comic/add?source_document_id={hitomi_id}&source_id=1'
                    await event.reply(f'存在需手动录入的tag, 请前往网页进行添加\n{redirect_url}')
                else:
                    resp = await client.post('/comic/add', json={'source_document_id': str(hitomi_id),
                                                                 'source_id': 1, 'inexistent_tags': {}})
                    redirect_url = f'{self.cm_config.base_url}/show_status'
                    await event.reply(f'tag已完备, 已提交录入任务, 访问网页以查看进度\n{redirect_url}')
        except HTTPStatusError as cm_e:
            logger.error(f'请求{resp.url}过程发生HTTP异常: {str(cm_e)}')
            await event.reply(f'请求{resp.url}过程发生HTTP异常: {str(cm_e)}')
        except RuntimeError as cm_e:
            logger.error(f'请求过程发生异常: {str(cm_e)}')
            await event.reply(f'请求过程发生异常: {str(cm_e)}')

    async def on_close(self) -> None:
        await super().on_close()

global_plugin_instance: Optional[UnnamedCmIntegrate] = None
