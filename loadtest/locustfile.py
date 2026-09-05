"""zhixue 压测脚本（locust）。

用法见同目录 README.md。默认只做只读压测；写操作与真实 LLM 调用
必须通过环境变量显式开启（会改数据 / 消耗真实费用）。

环境变量:
    LOADTEST_USERNAME / LOADTEST_PASSWORD   登录账号（默认 admin/admin123）
    LOADTEST_LLM=1                          开启内容生成 SSE 任务（真实调用 LLM，
                                            且会重新生成并覆盖该模块内容——只对
                                            专门的压测计划使用！）
"""

from __future__ import annotations

import os

from locust import HttpUser, between, task

LLM_ENABLED = os.getenv("LOADTEST_LLM") == "1"


class ZhixueUser(HttpUser):
    """一个虚拟用户 = 一个已登录的浏览器会话。"""

    wait_time = between(1, 3)  # 模拟真人浏览节奏

    def on_start(self) -> None:
        username = os.getenv("LOADTEST_USERNAME", "admin")
        password = os.getenv("LOADTEST_PASSWORD", "admin123")
        resp = self.client.post(
            "/api/auth/login",
            json={"username": username, "password": password},
            name="/api/auth/login",
        )
        if resp.status_code != 200:
            # 登录失败: 让该虚拟用户空转, 避免后续请求全是 401 噪音
            self.plan_id = None
            self.module_id = None
            self.disabled = True  # locust 停止调度该用户
            return
        self.client.headers["Authorization"] = f"Bearer {resp.json()['access_token']}"

        # 取一个真实计划/模块，供详情类任务使用（只读，不改数据）
        self.plan_id: str | None = None
        self.module_id: str | None = None
        items = self.client.get("/api/plans", name="/api/plans").json()
        if items:
            self.plan_id = items[0]["id"]
            doc = self.client.get(f"/api/plans/{self.plan_id}", name="/api/plans/:id").json()
            modules = doc.get("plan", {}).get("modules", [])
            if modules:
                self.module_id = modules[0]["id"]

    @task(6)
    def list_plans(self) -> None:
        self.client.get("/api/plans", name="/api/plans")

    @task(3)
    def plan_detail(self) -> None:
        if self.plan_id:
            self.client.get(f"/api/plans/{self.plan_id}", name="/api/plans/:id")

    @task(2)
    def spa_index(self) -> None:
        self.client.get("/", name="/ [SPA index]")

    @task(2)
    def bookmarks(self) -> None:
        self.client.get("/api/annotations", name="/api/annotations")

    @task(1)
    def usage_summary(self) -> None:
        self.client.get("/api/usage/summary", name="/api/usage/summary")

    @task(1)
    def health(self) -> None:
        self.client.get("/api/health", name="/api/health [expect 401]")

    @task(1)
    def generate_content_sse(self) -> None:
        """内容生成（SSE 长连接）。

        ⚠️ 仅 LOADTEST_LLM=1 时执行：真实调用 LLM（计费、受供应商限流），
        并且会重新生成、覆盖该模块的学习内容——只对专门的压测计划使用。
        并发请控制在个位数（压测意图是验证 SSE 长连接与nginx 链路，不是压垮供应商）。
        """
        if not LLM_ENABLED or not (self.plan_id and self.module_id):
            return
        with self.client.post(
            f"/api/plans/{self.plan_id}/modules/{self.module_id}/content",
            stream=True,
            timeout=300,
            name="/content [SSE generate]",
            catch_response=True,
        ) as resp:
            if resp.status_code != 200:
                resp.failure(f"status {resp.status_code}")
                return
            done = False
            for line in resp.iter_lines():
                if line.startswith("event: done"):
                    done = True
                    break
            if not done:
                resp.failure("stream ended without done event")
