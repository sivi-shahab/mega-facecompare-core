#  Copyright (c) 2020 the original author or authors
#
#  Licensed under the Apache License, Version 2.0 (the "License");
#  you may not use this file except in compliance with the License.
#  You may obtain a copy of the License at
#
#       https://www.apache.org/licenses/LICENSE-2.0
#
#  Unless required by applicable law or agreed to in writing, software
#  distributed under the License is distributed on an "AS IS" BASIS,
#  WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express
#  or implied. See the License for the specific language governing
#  permissions and limitations under the License.

import io
import logging

import imageio
import numpy as np

from src.constants import ENV
from src.exceptions import ImageReadLibraryError, ImageTooLargeError, OneDimensionalImageIsGivenError
from src.services.imgtools.types import Array3D

logger = logging.getLogger(__name__)

_TIFF_MAGIC = (b'II*\x00', b'MM\x00*', b'II+\x00', b'MM\x00+')


def _grayscale_to_rgb(img):
    """ Source: facenet library, to_rgb() function """
    w, h = img.shape
    ret = np.empty((w, h, 3), dtype=np.uint8)
    ret[:, :, 0] = ret[:, :, 1] = ret[:, :, 2] = img
    return ret


def _as_bytes(file):
    """Returns the raw bytes of an upload (werkzeug FileStorage / file-like / bytes), or None for a path."""
    if isinstance(file, (bytes, bytearray)):
        return bytes(file)
    if hasattr(file, 'read'):
        data = file.read()
        if hasattr(file, 'seek'):
            file.seek(0)
        return data
    return None


def _probe_pixels(data: bytes):
    """Reads only the image header to get width * height without decoding pixel data."""
    try:
        from PIL import Image
        with Image.open(io.BytesIO(data)) as im:
            width, height = im.size
            return width * height
    except Exception as e:
        if e.__class__.__name__.startswith('DecompressionBomb'):
            return float('inf')
    if data[:4] in _TIFF_MAGIC:
        try:
            import tifffile
            with tifffile.TiffFile(io.BytesIO(data)) as tif:
                pixels = 0
                for page in tif.pages:
                    shape = page.shape
                    pixels = max(pixels, int(np.prod(shape[:2])) if len(shape) >= 2 else 0)
                return pixels
        except Exception:
            pass
    return None


def read_img(file) -> Array3D:
    data = _as_bytes(file)
    source = file
    if data is not None:
        # Security fix (audit NV-08): bound the decoded size BEFORE allocating the full pixel array, so a small
        # highly compressed upload cannot exhaust the memory shared by all workers of the core pod.
        pixels = _probe_pixels(data)
        if pixels is not None and pixels > ENV.MAX_IMAGE_PIXELS:
            logger.warning("Rejected image with %d pixels (limit %d)", pixels, ENV.MAX_IMAGE_PIXELS)
            raise ImageTooLargeError
        source = data
    try:
        from PIL import Image
        Image.MAX_IMAGE_PIXELS = ENV.MAX_IMAGE_PIXELS
    except Exception:
        pass
    try:
        arr = imageio.imread(source)
    except (ValueError, SyntaxError) as e:
        raise ImageReadLibraryError from e
    except Exception as e:
        # e.g. PIL.Image.DecompressionBombError
        if e.__class__.__name__.startswith('DecompressionBomb'):
            raise ImageTooLargeError from e
        raise

    if arr.ndim < 2:
        raise OneDimensionalImageIsGivenError
    elif arr.ndim == 2:
        arr = _grayscale_to_rgb(arr)
    else:
        arr = arr[:, :, 0:3]

    return arr
