def test_event_bus_publish():
    from app.events.event_bus import EventBus

    bus = EventBus()
    called = []

    class Handler:
        def notify(self, event_type, payload):
            called.append(payload)

    handler = Handler()

    bus.subscribe("TEST_EVENT", handler)
    bus.publish("TEST_EVENT", {"x": 1})

    assert called[0]["x"] == 1