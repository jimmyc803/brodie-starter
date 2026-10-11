"""The end of a coached call: save the session (facetime/session_sink.py) and show the heat map on the call (facetime/recap_video.py).

The worker makes one CallRecap per bound caller when DEMO_CLIENT_ID is set (or --save-session), feeds it every event from the
loop (on_event: memory only), and calls `await finish(room, show=...)` when the plan is done (show=True: the room is still up)
or the call ends (show=False). Network work runs in a thread with a timeout; nothing here raises into the worker.
"""
import asyncio
import os

from facetime.session_sink import SessionSink, _log


class CallRecap:
    def __init__(self, plan, assignment=None, client_id=None, db=None):
        assignment = assignment or {}
        self.sink = SessionSink(client_id or os.environ.get('DEMO_CLIENT_ID'), assignment.get('program_day_id'),
                                assignment.get('items'), plan, db=db)
        self.started = False; self.start_task = None
        self.finished = None              # the asyncio task of finish(), so the 'done' path and the hang-up path share it
        self.show_task = None

    async def start(self):
        if self.started: return
        self.started = True
        try:
            ids = await asyncio.wait_for(asyncio.get_running_loop().run_in_executor(None, self.sink.start), 8)
            _log(f"session {ids['session_id']} started (recap /r/{ids['share_token']})")
        except Exception as e:
            _log(f'session start failed (retried at finish): {type(e).__name__}: {e}')

    def on_event(self, ev):
        try: self.sink.on_event(ev)
        except Exception as e: _log(f'sink event failed: {type(e).__name__}: {e}')

    async def finish(self, room=None, show=False, reason='done', timeout=20):
        """Save once; when show and the room is connected, publish the heat map card as video (in the background)."""
        if self.finished is None:
            self.finished = asyncio.ensure_future(self._save(reason, timeout))
        view = await asyncio.shield(self.finished)
        if show and view is not None and room is not None and self.show_task is None:
            self.show_task = asyncio.create_task(self._show(room, view), name='recap-video')
        return view

    async def _save(self, reason, timeout):
        loop = asyncio.get_running_loop()
        try:
            return await asyncio.wait_for(loop.run_in_executor(None, self.sink.finish, reason), timeout)
        except Exception as e:
            _log(f'session save failed or slow ({type(e).__name__}: {e}); the write may still finish in its thread')
            return self.sink._view                # built before any network: the card can still show

    async def _show(self, room, view):
        from facetime.recap_video import get_recap_png, publish_recap
        try:
            png = await asyncio.wait_for(asyncio.get_running_loop().run_in_executor(None, get_recap_png, view), 15)
            _log(f"heat map on the call ({len(png)} bytes); web recap /r/{view['session']['share_token']}")
            await publish_recap(room, png)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            _log(f'recap video failed: {type(e).__name__}: {e}')

    async def aclose(self, timeout=12):
        """Hang-up path: save if not saved yet (bounded), stop the card."""
        try: await asyncio.wait_for(self.finish(reason='call ended'), timeout)
        except Exception as e: _log(f'save on hang-up: {type(e).__name__}: {e}')
        if self.show_task is not None and not self.show_task.done():
            self.show_task.cancel()
