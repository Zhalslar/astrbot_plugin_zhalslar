import asyncio
import os
import yaml
from astrbot.api.event import filter
from astrbot.api.star import Context, Star
from astrbot.core.config.astrbot_config import AstrBotConfig
from astrbot.core.platform.astr_message_event import AstrMessageEvent
from astrbot.core.star.star import star_registry
from astrbot.core.utils.astrbot_path import get_astrbot_plugin_path
from astrbot.api import logger

DEFAULT_REPO_PREFIX = "https://github.com/Zhalslar/astrbot_plugin_"


def normalize_repo_url(item: str) -> str:
    """将插件名（如 zt、astrbot_plugin_zt）或完整仓库 URL 统一解析为完整 GitHub 仓库地址"""
    item = item.strip()
    if item.startswith("http://") or item.startswith("https://") or item.startswith("git@"):
        return item
    clean_name = item.lower()
    if clean_name.startswith("astrbot_plugin_"):
        clean_name = clean_name[len("astrbot_plugin_"):]
    return f"{DEFAULT_REPO_PREFIX}{clean_name}"


def get_plugin_short_name(item: str) -> str:
    """提取插件简短名称，如 zt"""
    clean = item.strip().rstrip("/").lower().split("/")[-1]
    if clean.endswith(".git"):
        clean = clean[:-4]
    if clean.startswith("astrbot_plugin_"):
        clean = clean[len("astrbot_plugin_"):]
    return clean


class ZhalslarBundlePlugin(Star):
    def __init__(self, context: Context, config: AstrBotConfig):
        super().__init__(context)
        self.config = config
        self.context = context
        self.auto_install = self.config.get("auto_install_on_startup", True)
        self.only_admin = self.config.get("only_admin", True)
        raw_plugins = self.config.get("bundle_plugins", [])
        self.bundle_plugins = [normalize_repo_url(p) for p in raw_plugins if str(p).strip()]

        if self.auto_install:
            asyncio.create_task(self._startup_install())

    async def _startup_install(self):
        await asyncio.sleep(5)  # 等待 AstrBot 初始化完成
        logger.info("[ZhalslarBundle] 正在检查并自动安装缺失的捆绑插件...")
        await self._install_plugins()

    def _get_installed_identifiers(self) -> set[str]:
        installed = set()

        # 1. 运行时注册的 star_registry
        for metadata in star_registry:
            repo = getattr(metadata, "repo", None)
            if repo:
                clean = repo.strip().rstrip("/").lower()
                installed.add(clean)
                installed.add(get_plugin_short_name(clean))
            root_dir = getattr(metadata, "root_dir_name", None)
            if root_dir:
                installed.add(root_dir.lower())
                installed.add(get_plugin_short_name(root_dir))
            if metadata.name:
                installed.add(metadata.name.lower())
                installed.add(get_plugin_short_name(metadata.name))

        # 2. 本地插件存储目录兜底
        pm = getattr(self.context, "_star_manager", None)
        plugin_path = getattr(pm, "plugin_store_path", None) or get_astrbot_plugin_path()
        if os.path.exists(plugin_path):
            for d in os.listdir(plugin_path):
                installed.add(d.lower())
                installed.add(get_plugin_short_name(d))
                meta_file = os.path.join(plugin_path, d, "metadata.yaml")
                if os.path.isfile(meta_file):
                    try:
                        with open(meta_file, "r", encoding="utf-8") as f:
                            data = yaml.safe_load(f)
                            if isinstance(data, dict):
                                repo = data.get("repo")
                                if repo:
                                    clean = repo.strip().rstrip("/").lower()
                                    installed.add(clean)
                                    installed.add(get_plugin_short_name(clean))
                                name = data.get("name")
                                if name:
                                    installed.add(name.lower())
                                    installed.add(get_plugin_short_name(name))
                    except Exception:
                        pass

        return installed

    async def _install_plugins(self, target_urls: list[str] = None, event: AstrMessageEvent = None):
        pm = getattr(self.context, "_star_manager", None)
        if not pm:
            msg = "[ZhalslarBundle] 无法获取 AstrBot 插件管理器实例。"
            logger.error(msg)
            if event:
                yield event.plain_result(msg)
            return

        installed = self._get_installed_identifiers()
        targets = target_urls if target_urls is not None else self.bundle_plugins

        to_install = []
        for url in targets:
            norm_url = normalize_repo_url(url)
            short_name = get_plugin_short_name(norm_url)
            clean_repo = norm_url.strip().rstrip("/").lower()
            if target_urls is not None:
                # 指定安装时不跳过
                to_install.append(norm_url)
            else:
                if clean_repo not in installed and short_name not in installed:
                    to_install.append(norm_url)

        if not to_install:
            msg = "所有捆绑插件均已安装完毕！"
            logger.info(f"[ZhalslarBundle] {msg}")
            if event:
                yield event.plain_result(msg)
            return

        total = len(to_install)
        if event:
            yield event.plain_result(f"检测到 {total} 个待安装插件，开始安装，请稍候...")

        success_count = 0
        fail_count = 0
        for idx, repo_url in enumerate(to_install, 1):
            short_name = get_plugin_short_name(repo_url)
            logger.info(f"[ZhalslarBundle] 正在安装 ({idx}/{total}): {repo_url}")
            try:
                await pm.install_plugin(repo_url=repo_url)
                success_count += 1
            except Exception as e:
                logger.error(f"[ZhalslarBundle] 安装插件失败 {repo_url}: {e}")
                fail_count += 1
            await asyncio.sleep(1)

        result_msg = f"插件安装完成！\n成功: {success_count} 个\n失败: {fail_count} 个"
        logger.info(f"[ZhalslarBundle] {result_msg}")
        if event:
            yield event.plain_result(result_msg)

    @filter.command_group("zhalslar")
    def zhalslar_group(self):
        pass

    @zhalslar_group.command("install")
    async def install_cmd(self, event: AstrMessageEvent, plugin_name: str = ""):
        """一键安装/更新所有捆绑插件，或指定安装单个插件（如：/zhalslar install zt）"""
        if self.only_admin and not event.is_admin():
            yield event.plain_result("只有管理员可以使用该指令。")
            return

        target_urls = None
        if plugin_name and plugin_name.strip():
            target_urls = [normalize_repo_url(plugin_name.strip())]

        async for res in self._install_plugins(target_urls=target_urls, event=event):
            yield res

    @zhalslar_group.command("list")
    async def list_cmd(self, event: AstrMessageEvent):
        """查看捆绑插件列表"""
        if self.only_admin and not event.is_admin():
            yield event.plain_result("只有管理员可以使用该指令。")
            return
        installed = self._get_installed_identifiers()
        lines = ["=== Zhalslar 捆绑插件列表 ==="]
        for url in self.bundle_plugins:
            norm_url = normalize_repo_url(url)
            short_name = get_plugin_short_name(norm_url)
            clean_repo = norm_url.strip().rstrip("/").lower()
            status = "已安装" if (clean_repo in installed or short_name in installed) else "未安装"
            lines.append(f"- [{status}] {short_name} ({norm_url})")
        yield event.plain_result("\n".join(lines))
