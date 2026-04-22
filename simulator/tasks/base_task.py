"""
Nha Kinh Thong Minh - Base Task (Abstract Base Class)
======================================================
Moi task trong he thong phai ke thua BaseTask.
Dam bao contract chung cho Cooperative Scheduler.

Nguyen tac:
  - run()      : Thuc thi 1 tick. KHONG duoc block.
  - shutdown() : Giai phong tai nguyen khi dung he thong.
"""

from abc import ABC, abstractmethod


class BaseTask(ABC):
    """
    Abstract Base Class cho tat ca cac task trong he thong.
    
    Scheduler chi chap nhan cac task ke thua tu class nay,
    dam bao moi task co interface thong nhat (Open-Closed Principle).
    """

    @abstractmethod
    def run(self) -> None:
        """
        Thuc thi mot vong lap cua task.
        
        KHONG duoc block (cooperative multitasking).
        Phai tra quyen dieu khien ngay khi xong.
        """
        ...

    @abstractmethod
    def shutdown(self) -> None:
        """
        Giai phong tai nguyen khi dung he thong.
        
        Vi du: dong ket noi DB, dong socket, flush buffer.
        Neu khong can cleanup, implement voi `pass`.
        """
        ...
