import json
from pathlib import Path


DEFAULT_ROLES = {
    "default": (
        "你是茗懿，一个友好、简洁、可靠的中文 QQ 群聊助手。"
        "优先直接回答用户的问题，不确定时明确说明不确定点。"
        "涉及日期、天气、新闻、价格、政策、产品发售等实时信息时，先核验再回答，不要凭记忆猜测。"
        "回答要适合聊天场景，避免冗长。"
    ),
    "assistant": (
        "你是一个严谨的中文助手。回答要结构清晰、信息准确、语气自然。"
        "当问题缺少必要条件时，先说明假设，再给出可执行建议。"
        "涉及实时信息时必须核验，不要把未经验证的日期或事实当成确定结论。"
    ),
    "creative": (
        "你是一个擅长创意讨论的聊天伙伴。回答可以更有想象力，"
        "但不要牺牲事实准确性；涉及实时信息或不确定事实时，要先核验或说清楚不确定。"
    ),
    "concise": (
        "你是一个极简风格中文助手。优先用短句回答，只保留必要信息。"
        "除非用户要求展开，否则不要写长篇解释。涉及实时信息时仍要先核验。"
    ),
    "jarvis": (
        "你是一个受经典科幻智能管家启发的中文 AI 助手，而不是任何现有作品角色本身。"
        "你的语气沉稳、克制、礼貌，带一点英式管家式的从容和轻微幽默。"
        "优先理解用户真实意图，主动补足必要背景，给出清晰可执行的建议。"
        "可以在合适时称呼用户为“先生”或“女士”，但不要过度使用。"
        "面对复杂任务时先简要判断局势，再给出方案、风险和下一步。"
        "涉及实时信息、日期、天气、新闻、价格、政策或产品状态时，必须先核验或明确不确定性。"
        "不要编造自己拥有设备控制、传感器、系统权限或现实世界执行能力。"
    ),
}


class RoleStore:
    def __init__(self, roles_path: str, default_role: str) -> None:
        self.path = Path(roles_path)
        self.default_role = default_role
        self.roles: dict[str, str] = {}
        self.reload()

    def reload(self) -> None:
        self._ensure_file()
        with self.path.open("r", encoding="utf-8") as file:
            loaded = json.load(file)

        roles = loaded.get("roles", loaded)
        if not isinstance(roles, dict):
            roles = {}

        self.roles = {
            str(name): str(prompt)
            for name, prompt in roles.items()
            if str(name).strip() and str(prompt).strip()
        }
        if self.default_role not in self.roles:
            self.roles[self.default_role] = DEFAULT_ROLES.get(
                self.default_role,
                DEFAULT_ROLES["default"],
            )

    def get_prompt(self, role_name: str) -> str:
        return self.roles.get(role_name) or self.roles[self.default_role]

    def has_role(self, role_name: str) -> bool:
        return role_name in self.roles

    def list_roles(self) -> list[str]:
        return sorted(self.roles)

    def _ensure_file(self) -> None:
        if self.path.exists():
            return

        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("w", encoding="utf-8") as file:
            json.dump({"roles": DEFAULT_ROLES}, file, ensure_ascii=False, indent=2)
