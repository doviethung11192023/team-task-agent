# app/tools/risk_tools.py
from app.database.supabase_client import db
from app.models.schemas import AgentResponse
from typing import List, Dict
from langsmith import traceable

@traceable(name="Risk Tools")
class RiskTools:
    
    @staticmethod
    def create_risks(project_id: str, risks: List[Dict]) -> AgentResponse:
        """Tạo nhiều rủi ro cùng lúc"""
        try:
            saved_risks = db.create_risks_batch(risks)
            return AgentResponse(
                response=f"✅ Đã tạo {len(saved_risks)} rủi ro cho project.",
                risks=saved_risks,
                success=True
            )
        except Exception as e:
            return AgentResponse(
                response=f"❌ Lỗi khi tạo rủi ro: {str(e)}",
                success=False
            )

    @staticmethod
    def get_project_risks(project_id: str) -> List[Dict]:
        """Lấy danh sách rủi ro của project"""
        return db.get_risks_by_project(project_id)

    @staticmethod
    def update_risk_status(risk_id: str, status: str, actual_outcome: str = None):
        """Cập nhật trạng thái rủi ro"""
        db.update_risk_status(risk_id, status, actual_outcome)
        return {"success": True, "message": f"Đã cập nhật risk {risk_id} thành {status}"}


# Instance
risk_tools = RiskTools()