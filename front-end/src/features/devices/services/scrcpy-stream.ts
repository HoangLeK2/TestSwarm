import { farmApi } from '@/lib/farm-api';
import { createSingleFlight } from '../lib/single-flight';

const SCRCPY_STREAM_TIMEOUT_MS = 10_000;

export const attachScrcpyStream = createSingleFlight(
  async (serial: string) => {
    const { data } = await farmApi.post(
      `/devices/${encodeURIComponent(serial)}/scrcpy/attach`,
      {},
      { timeout: SCRCPY_STREAM_TIMEOUT_MS }
    );
    return data;
  },
  (serial) => serial
);

export const detachScrcpyStream = createSingleFlight(
  async (serial: string) => {
    const { data } = await farmApi.post(
      `/devices/${encodeURIComponent(serial)}/scrcpy/detach`,
      {},
      { timeout: SCRCPY_STREAM_TIMEOUT_MS }
    );
    return data;
  },
  (serial) => serial
);
