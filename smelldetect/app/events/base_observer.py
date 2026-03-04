from abc import ABC, abstractmethod

class Observer(ABC):

    @abstractmethod
    def notify(self, event_type: str, data: dict):
        pass