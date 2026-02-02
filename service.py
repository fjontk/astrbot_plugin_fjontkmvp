from typing import Any, Dict, List, Optional
from astrbot.api.event import AstrMessageEvent
from astrbot.api.star import Context, Star
from astrbot.api import AstrBotConfig

class InjectionService:
    def __init__(self, plugin: Star, config: AstrBotConfig):
        self.plugin = plugin
        self.config = config

    def check_whitelist(self, event: AstrMessageEvent) -> bool:
        """检查白名单。如果未开启白名单模式，直接通过。"""
        if not self.config.get("whitelist_mode", False):
            return True
        
        whitelist = self.config.get("whitelist", [])
        return event.unified_msg_origin in whitelist or event.get_group_id() in whitelist

    def get_storage_key(self, event: AstrMessageEvent) -> str:
        """生成基于会话的存储键"""
        return f"injection_{event.unified_msg_origin}"
    
    async def get_injections(self, event: AstrMessageEvent) -> List[Dict[str, Any]]:
        key = self.get_storage_key(event)
        data = await self.plugin.get_kv_data(key, {})
        return data.get("injections", [])

    async def add_injection(self, event: AstrMessageEvent, type_name: str, content: str, turns: int) -> tuple[bool, str]:
        """添加注入条目。返回 (是否成功, 消息)"""
        key = self.get_storage_key(event)
        data = await self.plugin.get_kv_data(key, {})
        
        if "injections" not in data:
            data = {"injections": []}

        max_items = self.config.get("max_injections_per_session", 5)
        if len(data["injections"]) >= max_items:
            return False, f"❌ 注入条目已达上限 ({max_items})。请先清除部分条目。"

        new_entry = {
            "type": type_name,
            "content": content,
            "turns_left": turns,
            "original_turns": turns
        }
        data["injections"].append(new_entry)
        
        await self.plugin.put_kv_data(key, data)
        return True, ""

    async def clear_injections(self, event: AstrMessageEvent):
        key = self.get_storage_key(event)
        await self.plugin.delete_kv_data(key)

    async def get_formatted_injection_text(self, event: AstrMessageEvent) -> str:
        """获取需要注入的文本，并自动更新轮次"""
        key = self.get_storage_key(event)
        data = await self.plugin.get_kv_data(key, None)

        if not data or "injections" not in data or not data["injections"]:
            return ""

        injections = data["injections"]
        active_injections = []
        injection_text = ""
        has_change = False

        # Get templates
        task_tmpl = self.config.get("task_prompt_template", "\n[Current Task]\n{content}\n")
        know_tmpl = self.config.get("knowledge_prompt_template", "\n[Additional Knowledge]\n{content}\n")

        for item in injections:
            if item["turns_left"] > 0:
                # Use template based on type
                tmpl = task_tmpl if item["type"] == "task" else know_tmpl
                try:
                    # Replace {content} with actual content
                    # Also handle if user put literal \n in config string, though typically JSON handles it.
                    # AstrBot config might pass as raw string.
                    formatted_content = tmpl.replace("{content}", item["content"])
                    injection_text += formatted_content
                except Exception:
                    # Fallback
                    header = "[Current Task]" if item["type"] == "task" else "[Additional Knowledge]"
                    injection_text += f"\n**{header}**\n{item['content']}\n"
                
                item["turns_left"] -= 1
                if item["turns_left"] > 0:
                    active_injections.append(item)
                has_change = True
            else:
                has_change = True

        if has_change:
            if not active_injections:
                await self.plugin.delete_kv_data(key)
            else:
                data["injections"] = active_injections
                await self.plugin.put_kv_data(key, data)
        
        return injection_text
