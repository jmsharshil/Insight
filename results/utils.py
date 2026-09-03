import logging
from chat.notifications import send_system_notification
from students.models import ParentLink

logger = logging.getLogger(__name__)

def notify_students_and_parents_of_exam_result(published_results):
    """
    Send push notifications to the students and parents of students whose exam results have been published.
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

                    # WhatsApp: notify parent
                    try:
                        if getattr(link.parent, 'phone', None):
                            from chat.notifications import send_whatsapp_with_fallback
                            rank_str = str(pr.rank) if getattr(pr, 'rank', None) else 'N/A'
                            send_whatsapp_with_fallback(
                                to=link.parent.phone,
                                template_name="result_published_",
                                language_code="en",
                                components=[{
                                    "type": "body",
                                    "parameters": [
                                        {"type": "text", "text": link.parent.name},
                                        {"type": "text", "text": exam_title},
                                        {"type": "text", "text": str(pr.marks_obtained)},
                                        {"type": "text", "text": str(pr.total_marks)},
                                        {"type": "text", "text": str(pr.percentage)},
                                        {"type": "text", "text": rank_str},
                                    ]
                                }],
                                fallback_body=body,
                                user_id=str(link.parent.id),
                            )
                    except Exception as wa_err:
                        logger.error(f"[Result Published] WhatsApp to parent {link.parent.id} failed: {wa_err}")
            
            # Notify the student
            try:
                if pr.student and hasattr(pr.student, 'user') and pr.student.user:
                    title = "Exam Result Published"
                    exam_title = pr.exam.title if pr.exam else "Unknown Exam"
                    body = f"Your result for '{exam_title}' has been published. Marks: {pr.marks_obtained}/{pr.total_marks} ({pr.percentage}%)."
                    
                    send_system_notification(
                        user_id=str(pr.student.user.id),
                        title=title,
                        body=body,
                        metadata={
                            "type": "exam_result",
                            "exam_id": str(pr.exam.id) if pr.exam else "",
                            "student_id": str(pr.student.id),
                            "result_id": str(pr.id)
                        }
                    )

                    # WhatsApp: notify student
                    try:
                        if getattr(pr.student.user, 'phone', None):
                            from chat.notifications import send_whatsapp_with_fallback
                            student_name = pr.student.user.name
                            rank_str = str(pr.rank) if getattr(pr, 'rank', None) else 'N/A'
                            send_whatsapp_with_fallback(
                                to=pr.student.user.phone,
                                template_name="result_published_",
                                language_code="en",
                                components=[{
                                    "type": "body",
                                    "parameters": [
                                        {"type": "text", "text": student_name},
                                        {"type": "text", "text": exam_title},
                                        {"type": "text", "text": str(pr.marks_obtained)},
                                        {"type": "text", "text": str(pr.total_marks)},
                                        {"type": "text", "text": str(pr.percentage)},
                                        {"type": "text", "text": rank_str},
                                    ]
                                }],
                                fallback_body=body,
                                user_id=str(pr.student.user.id),
                            )
                    except Exception as wa_err:
                        logger.error(f"[Result Published] WhatsApp to student {pr.student.id} failed: {wa_err}")
            except Exception as e:
                logger.error(f"Failed to notify student for published result {pr.id}: {e}")

        except Exception as e:
            logger.error(f"Failed to notify parents for published result {pr.id}: {e}")
