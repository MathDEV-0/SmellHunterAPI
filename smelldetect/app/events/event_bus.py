class EventBus:

    def __init__(self):
        self._observers = {}

    def subscribe(self, event_type: str, observer):
        if event_type not in self._observers:
            self._observers[event_type] = []
        self._observers[event_type].append(observer)

    def publish(self, event_type: str, data: dict):
        observers = self._observers.get(event_type, [])
        for obs in observers:
            obs.notify(event_type, data)