from observability.base_observability import BaseObservability
from schemas.events import Event
from schemas.trace import AgentTrace


class LocalObservability(BaseObservability):

    async def log_event(
        self,
        event: Event
    ):
        print(
            f"""
        [EVENT]

        Session ID : {event.session_id}

        Type       : {event.event_type}

        Message    : {event.message}
        """
        )

    async def create_trace(
        self,
        trace: AgentTrace
    ):
        print(
            f"""
    [TRACE]

    Session ID : {trace.session_id}

    Input      : {trace.input_data}

    Reasoning  : {trace.reasoning}

    Output     : {trace.output_data}
    """
        )