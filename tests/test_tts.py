from __future__ import annotations

import time
from unittest.mock import patch

from app.audio.tts import Speaker


class FakeProcess:
    def __init__(self, command, **kwargs):
        self.command = command
        self.started = time.monotonic()

    def wait(self):
        time.sleep(0.01)


def test_speaker_queues_without_interrupting():
    with patch('app.audio.tts.shutil.which', return_value='/usr/bin/say'), patch(
        'app.audio.tts.subprocess.Popen', side_effect=FakeProcess
    ) as popen:
        speaker = Speaker(voice='Mónica', rate=190)
        try:
            assert speaker.say('Primera frase', 'P1')
            assert speaker.say('Segunda frase', 'P2')
            speaker._queue.join()
        finally:
            speaker.shutdown()

        assert popen.call_count == 2
        assert popen.call_args_list[0].args[0][-1] == 'Primera frase'
        assert popen.call_args_list[1].args[0][-1] == 'Segunda frase'
