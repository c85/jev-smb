import base64

import numpy as np

from mario_jev.dashboard import frame_data_url


def test_frame_data_url_encodes_rgb_png():
    frame = np.zeros((2, 3, 3), dtype=np.uint8)
    payload = frame_data_url(frame)
    encoded = payload.removeprefix("data:image/png;base64,")

    assert payload.startswith("data:image/png;base64,")
    assert base64.b64decode(encoded).startswith(bytes([137]) + b"PNG")
