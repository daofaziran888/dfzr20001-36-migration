"""业务路由汇总：所有模块共用一套资源路由，流水线路由独立注册。"""
from __future__ import annotations

from app.routers import resource, pipeline_routes, pan_routes

# 固定前缀路由（/api/pipeline、/api/pan）必须先于通用 /api/{module} 注册，
# 否则 /api/pan/state 这类路径会被通用动态路由按 entry_id 解析成 422。
ROUTERS = [pipeline_routes, pan_routes, resource]