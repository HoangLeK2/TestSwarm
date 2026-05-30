import 'axios';

declare module 'axios' {
  export interface AxiosRequestConfig {
    _retry?: boolean;
    _429RetryCount?: number;
    _skip429Retry?: boolean;
  }
}
