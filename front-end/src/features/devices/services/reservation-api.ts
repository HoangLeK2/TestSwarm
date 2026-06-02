import { getDeviceFarmApi } from '@/features/device-farm/services/client';

export const deviceReservationApi = {
  reserve: async (serial: string) => {
    const res =
      await getDeviceFarmApi().api.apiDevicesReserveApiDevicesSerialReservePost(
        serial
      );
    return res.data;
  },
  release: async (serial: string) => {
    const res =
      await getDeviceFarmApi().api.apiDevicesReleaseApiDevicesSerialReleasePost(
        serial
      );
    return res.data;
  }
};
