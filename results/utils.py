import logging
from chat.notifications import send_system_notification
from students.models import ParentLink

logger = logging.getLogger(__name__)

def notify_parents_of_exam_result(published_results):
    """
    Send push notifications to the parents of students whose exam results have been published.
    """
    for pr in published_results:
        try:
            # Get all parents linked to this student
            parents = ParentLink.objects.filter(student=pr.student).select_related('parent', 'student__user')
            
            for link in parents:
                if link.parent:
                    title = "Exam Result Published"
                    exam_title = pr.exam.title if pr.exam else "Unknown Exam"
                    try:
                        student_name = pr.student.user.name if hasattr(pr.student, 'user') else str(pr.student)
                    except Exception:
                        student_name = str(pr.student)
                        
                    body = f"The result for '{exam_title}' has been published for {student_name}. Marks: {pr.marks_obtained}/{pr.total_marks} ({pr.percentage}%)."
                    
                    send_system_notification(
                        user_id=str(link.parent.id),
                        title=title,
                        body=body,
                        metadata={
                            "type": "exam_result",
                            "exam_id": str(pr.exam.id) if pr.exam else "",
                            "student_id": str(pr.student.id) if pr.student else "",
                            "result_id": str(pr.id)
                        }
                    )
        except Exception as e:
            logger.error(f"Failed to notify parents for published result {pr.id}: {e}")
