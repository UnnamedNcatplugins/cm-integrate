from dataclasses import dataclass, InitVar, field, fields, MISSING
from typing import Optional, Any
from ncatbot.plugin_system import NcatBotPlugin
from ncatbot.utils import get_log
import yaml
import enum

logger = get_log('ConfigProxy')


def yaml_dump_enum(dumper, data):
    return dumper.represent_data(data.value)
yaml.add_multi_representer(enum.Enum, yaml_dump_enum)


@dataclass
class ProxiedPluginConfig:
    plugin: InitVar[NcatBotPlugin] = field(default=None)

    def __post_init__(self, plugin: Optional[NcatBotPlugin] = None):
        if plugin:
            self._register_defaults(plugin.config, plugin)

    def _register_defaults(self, current_dict: dict, plugin: Optional[NcatBotPlugin] = None):
        nested_instances: dict[str, ProxiedPluginConfig] = {}
        for f in fields(self):
            if isinstance(f.type, type) and issubclass(f.type, ProxiedPluginConfig):
                logger.debug(f"发现嵌套配置: {f.name}, 类型: {f.type}")
                if plugin:
                    plugin.register_config(f.name, {}, value_type=dict)
                else:
                    if f.name not in current_dict:
                        current_dict[f.name] = {}
                temp_child = f.type()
                temp_child._register_defaults(current_dict[f.name])
                nested_instances[f.name] = temp_child
            else:
                default_val = None
                if f.default is not MISSING:
                    default_val = f.default
                if f.default_factory is not MISSING:
                    default_val = f.default_factory()
                if default_val is None:
                    raise TypeError(f'字段 {f.name} 必须给定初始值')
                if plugin:
                    logger.debug(f"注册普通配置: {f.name} = {default_val}")
                    plugin.register_config(f.name, default_val, value_type=type(default_val))
                else:
                    if f.name not in current_dict:
                        current_dict[f.name] = default_val
        self._data_source = current_dict
        self._nested_instances = nested_instances

    def __getattribute__(self, name: str):
        if '_nested_instances' not in object.__getattribute__(self, '__dict__'):
            return super().__getattribute__(name)
        data_source: dict = object.__getattribute__(self, "_data_source")
        nested_instances: dict[str, ProxiedPluginConfig] = object.__getattribute__(self, '_nested_instances')
        try:
            value = data_source[name]
        except KeyError:
            return super().__getattribute__(name)
        if name in nested_instances:
            return nested_instances[name]
        return value

    def __setattr__(self, name: str, value: Any):
        if '_nested_instances' not in object.__getattribute__(self, '__dict__'):
            object.__setattr__(self, name, value)
            return
        data_source = object.__getattribute__(self, "_data_source")
        nested_instances: dict[str, ProxiedPluginConfig] = object.__getattribute__(self, '_nested_instances')
        if name in nested_instances:
            if not issubclass(value, ProxiedPluginConfig):
                raise TypeError(f'不允许对属性值 {name} 直接写入 {value}')
            if type(value) is not nested_instances[name]:
                raise TypeError(f'目标值 {value} 不是 {nested_instances[name]} 的实例')
        data_source[name] = value

    def __repr__(self):
        # 打印时显示底层字典的数据，而不是 dataclass 的初始值
        return f"{self.__class__.__name__}({object.__getattribute__(self, '_data_source')})"
