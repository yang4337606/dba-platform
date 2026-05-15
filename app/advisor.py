"""
智能建议增强模块

基于数据库画像和历史记录，提供个性化优化建议
"""

from app.models import db


class SmartAdvisor:
    """智能建议系统"""

    def __init__(self):
        self.db = db

    def generate_recommendations(self, result, db_identifier=None):
        """生成智能建议"""
        recommendations = []

        # 获取诊断信息
        result_dict = result.to_dict() if hasattr(result, 'to_dict') else {}
        main_problem = result_dict.get("diagnosis", {}).get("main_problem", "")
        metrics = result_dict.get("metrics", {})

        # 获取数据库画像
        profile = None
        if db_identifier:
            profile = self.db.get_profile(db_identifier)

        # 基于主要问题生成建议
        if "CPU" in main_problem or "cpu" in main_problem.lower():
            recommendations.extend(self._cpu_recommendations(metrics, profile))

        if "IO" in main_problem or "io" in main_problem.lower() or "读写" in main_problem:
            recommendations.extend(self._io_recommendations(metrics, profile))

        if "log file sync" in main_problem.lower():
            recommendations.extend(self._log_file_sync_recommendations(metrics, profile))

        if "锁" in main_problem or "lock" in main_problem.lower() or "latch" in main_problem.lower():
            recommendations.extend(self._lock_recommendations(metrics, profile))

        # 基于历史案例生成建议
        if main_problem:
            similar_cases = self.db.get_similar_cases(main_problem, limit=3)
            if similar_cases:
                recommendations.append({
                    "priority": "P2",
                    "category": "历史经验",
                    "action": f"参考历史案例：过去 {len(similar_cases)} 次遇到类似问题",
                    "reason": "查看历史记录了解之前的处理方式和效果",
                    "historical": True
                })

        # 去重和排序
        recommendations = self._deduplicate(recommendations, profile)
        recommendations.sort(key=lambda x: x["priority"])

        return recommendations

    def _cpu_recommendations(self, metrics, profile):
        """CPU相关建议"""
        recommendations = []

        cpu_percent = metrics.get("db_cpu_percent", 0)

        if cpu_percent > 80:
            recommendations.append({
                "priority": "P1",
                "category": "CPU优化",
                "action": "紧急优化高CPU消耗的SQL语句",
                "reason": f"DB CPU使用率达到 {cpu_percent:.1f}%，严重影响性能"
            })
        elif cpu_percent > 50:
            recommendations.append({
                "priority": "P2",
                "category": "CPU优化",
                "action": "优化CPU密集型SQL，考虑添加索引",
                "reason": f"DB CPU使用率 {cpu_percent:.1f}%，有优化空间"
            })

        # 检查是否已优化过
        if profile and profile.get("optimized_items"):
            optimized = profile["optimized_items"]
            if not any("索引" in item or "index" in item.lower() for item in optimized):
                recommendations.append({
                    "priority": "P2",
                    "category": "索引优化",
                    "action": "分析Top SQL，为高频查询添加合适的索引",
                    "reason": "历史记录显示尚未进行系统性索引优化"
                })

        return recommendations

    def _io_recommendations(self, metrics, profile):
        """IO相关建议"""
        recommendations = []

        recommendations.append({
            "priority": "P2",
            "category": "IO优化",
            "action": "检查存储性能，考虑使用SSD或优化存储配置",
            "reason": "IO等待是主要瓶颈"
        })

        recommendations.append({
            "priority": "P3",
            "category": "IO优化",
            "action": "优化SQL减少物理读，增加buffer cache命中率",
            "reason": "减少磁盘IO可显著提升性能"
        })

        return recommendations

    def _log_file_sync_recommendations(self, metrics, profile):
        """log file sync相关建议"""
        recommendations = []

        recommendations.append({
            "priority": "P1",
            "category": "日志优化",
            "action": "优化redo log配置，考虑使用更快的存储设备",
            "reason": "log file sync等待过高，影响事务提交性能"
        })

        # 检查是否已优化过
        if profile and profile.get("optimized_items"):
            optimized = profile["optimized_items"]
            if not any("redo" in item.lower() or "日志" in item for item in optimized):
                recommendations.append({
                    "priority": "P2",
                    "category": "日志优化",
                    "action": "调整redo log大小和数量，启用异步IO",
                    "reason": "历史记录显示尚未优化redo log配置"
                })

        return recommendations

    def _lock_recommendations(self, metrics, profile):
        """锁相关建议"""
        recommendations = []

        recommendations.append({
            "priority": "P1",
            "category": "锁优化",
            "action": "分析锁等待，优化事务逻辑减少锁持有时间",
            "reason": "锁竞争是主要瓶颈"
        })

        recommendations.append({
            "priority": "P2",
            "category": "锁优化",
            "action": "考虑调整隔离级别或使用乐观锁",
            "reason": "减少锁竞争可提升并发性能"
        })

        return recommendations

    def _deduplicate(self, recommendations, profile):
        """去重：移除已优化过的建议"""
        if not profile or not profile.get("optimized_items"):
            return recommendations

        optimized_items = profile["optimized_items"]
        filtered = []

        for rec in recommendations:
            # 检查是否已优化
            action = rec["action"].lower()
            already_done = False

            for item in optimized_items:
                item_lower = item.lower()
                # 简单的关键词匹配
                if any(keyword in action and keyword in item_lower
                       for keyword in ["索引", "index", "redo", "日志", "buffer", "锁"]):
                    already_done = True
                    break

            if not already_done:
                filtered.append(rec)
            else:
                # 添加提示：已优化
                rec["already_optimized"] = True
                rec["priority"] = "P9"  # 降低优先级
                filtered.append(rec)

        return filtered


# 全局实例
advisor = SmartAdvisor()
