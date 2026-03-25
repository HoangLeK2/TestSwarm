/* eslint-disable */
/* tslint:disable */
// @ts-nocheck
/*
 * ---------------------------------------------------------------
 * ## THIS FILE WAS GENERATED VIA SWAGGER-TYPESCRIPT-API        ##
 * ##                                                           ##
 * ## AUTHOR: acacode                                           ##
 * ## SOURCE: https://github.com/acacode/swagger-typescript-api ##
 * ---------------------------------------------------------------
 */

/**
 * AdbRegisterRequest
 * Body for app-after-scan: phone sends its IP so backend can connect via ADB.
 */
export interface AdbRegisterRequest {
  /** Ip */
  ip: string;
  /**
   * Port
   * @default 5555
   */
  port?: number;
  /** Device Key */
  device_key?: string | null;
}

/** AddDeviceBody */
export interface AddDeviceBody {
  /** Device Id */
  device_id: string;
}

/** CampaignCreate */
export interface CampaignCreate {
  /** Name */
  name: string;
  /**
   * Description
   * @default ""
   */
  description?: string;
  /**
   * Scenario
   * @default {}
   */
  scenario?: Record<string, any>;
  /**
   * Device Ids
   * @default []
   */
  device_ids?: string[];
}

/** CampaignDeviceOut */
export interface CampaignDeviceOut {
  /** Id */
  id: string;
  /** Serial */
  serial: string;
  /** Name */
  name: string;
}

/** CampaignOut */
export interface CampaignOut {
  /** Id */
  id: string;
  /** Name */
  name: string;
  /** Description */
  description: string;
  /** Status */
  status: string;
  /** Scenario */
  scenario?: Record<string, any> | null;
  /**
   * Scenarios
   * @default []
   */
  scenarios?: ScenarioOut[];
  /** User Id */
  user_id: string | null;
  /**
   * Created At
   * @format date-time
   */
  created_at: string;
}

/** CompileScenarioBody */
export interface CompileScenarioBody {
  /** Instructions */
  instructions?: string | null;
  /** Ui Xml */
  ui_xml?: string | null;
  /** Device Serial */
  device_serial?: string | null;
  /** Device Context */
  device_context?: Record<string, any> | null;
  /** Scenario Id */
  scenario_id?: string | null;
}

/**
 * ConnectByIpBody
 * Kết nối thiết bị qua ADB TCP: backend chủ động connect tới IP, không cần QR.
 */
export interface ConnectByIpBody {
  /** Ip */
  ip: string;
  /**
   * Port
   * @default 5555
   */
  port?: number;
}

/** DeviceCreate */
export interface DeviceCreate {
  /** Serial */
  serial: string;
  /**
   * Name
   * @default ""
   */
  name?: string;
  /** User Id */
  user_id?: string | null;
}

/** DeviceOut */
export interface DeviceOut {
  /** Id */
  id: string;
  /** Serial */
  serial: string;
  /** Name */
  name: string;
  /** Device Key */
  device_key: string;
  /** User Id */
  user_id: string | null;
  /** Brand */
  brand: string;
  /** Model */
  model: string;
  /** Android Version */
  android_version: string;
  /** Sdk Version */
  sdk_version: number;
  /** Screen Width */
  screen_width: number;
  /** Screen Height */
  screen_height: number;
  /** Last Seen */
  last_seen: string | null;
  /**
   * Created At
   * @format date-time
   */
  created_at: string;
  /** Adb Ip */
  adb_ip?: string | null;
  /**
   * Adb Port
   * @default 5555
   */
  adb_port?: number;
}

/** EndSessionRequest */
export interface EndSessionRequest {
  /** Session Id */
  session_id: string;
}

/** FleetRunRequest */
export interface FleetRunRequest {
  /** Steps */
  steps: Record<string, any>[];
  /**
   * Filter State
   * @default "READY"
   */
  filter_state?: string;
  /** Filter Model */
  filter_model?: string | null;
  /** Max Devices */
  max_devices?: number | null;
  /**
   * Priority
   * @default 5
   */
  priority?: number;
  /**
   * Timeout
   * @default 300
   */
  timeout?: number;
  /**
   * Max Retries
   * @default 1
   */
  max_retries?: number;
}

/** HTTPValidationError */
export interface HTTPValidationError {
  /** Detail */
  detail?: ValidationError[];
}

/** HitTestRequest */
export interface HitTestRequest {
  /**
   * X
   * @default 0
   */
  x?: number;
  /**
   * Y
   * @default 0
   */
  y?: number;
  /**
   * Rx
   * @default -1
   */
  rx?: number;
  /**
   * Ry
   * @default -1
   */
  ry?: number;
}

/** InputTextRequest */
export interface InputTextRequest {
  /** Text */
  text: string;
}

/** KeyRequest */
export interface KeyRequest {
  /** Key */
  key: string;
}

/** LoginRequest */
export interface LoginRequest {
  /** Email */
  email: string;
  /** Password */
  password: string;
}

/** LongTapRequest */
export interface LongTapRequest {
  /** X */
  x: number;
  /** Y */
  y: number;
  /**
   * Duration Ms
   * @default 800
   */
  duration_ms?: number;
}

/** OpenUrlRequest */
export interface OpenUrlRequest {
  /** Url */
  url: string;
  /** Package */
  package?: string | null;
}

/** OrganizationCreate */
export interface OrganizationCreate {
  /** Businessname */
  businessName: string;
  /** Businessemail */
  businessEmail?: string | null;
  /** Businesslogo */
  businessLogo?: string | null;
}

/** OrganizationOut */
export interface OrganizationOut {
  /** Id */
  id: string;
  /** Businessname */
  businessName: string;
  /** Businessemail */
  businessEmail: string | null;
  /** Businesslogo */
  businessLogo: string | null;
  /**
   * Created At
   * @format date-time
   */
  created_at: string;
}

/** PairBulkBody */
export interface PairBulkBody {
  /**
   * Count
   * @default 1
   */
  count?: number;
}

/** RefreshRequest */
export interface RefreshRequest {
  /** Refresh Token */
  refresh_token: string;
}

/** RegisterDeviceBody */
export interface RegisterDeviceBody {
  /**
   * Name
   * @default ""
   */
  name?: string;
  /**
   * Description
   * @default ""
   */
  description?: string;
}

/** RegisterRequest */
export interface RegisterRequest {
  /** Email */
  email: string;
  /** Name */
  name: string;
  /** Password */
  password: string;
  /**
   * Role
   * @default "operator"
   */
  role?: string;
}

/** ScenarioCreate */
export interface ScenarioCreate {
  /**
   * Name
   * @default "Scenario"
   */
  name?: string;
  /**
   * Instructions
   * @default ""
   */
  instructions?: string;
  /**
   * Steps
   * @default []
   */
  steps?: any[];
  /**
   * Order
   * @default 0
   */
  order?: number;
}

/** ScenarioOut */
export interface ScenarioOut {
  /** Id */
  id: string;
  /** Campaign Id */
  campaign_id: string;
  /** Name */
  name: string;
  /** Instructions */
  instructions: string;
  /** Steps */
  steps: any[];
  /** Order */
  order: number;
  /**
   * Created At
   * @format date-time
   */
  created_at: string;
  /**
   * Updated At
   * @format date-time
   */
  updated_at: string;
}

/** ScenarioPreviewRequest */
export interface ScenarioPreviewRequest {
  /** Steps */
  steps: Record<string, any>[];
}

/** ScenarioUpdate */
export interface ScenarioUpdate {
  /** Name */
  name?: string | null;
  /** Instructions */
  instructions?: string | null;
  /** Steps */
  steps?: any[] | null;
  /** Order */
  order?: number | null;
}

/** ScenarioUpdateBody */
export interface ScenarioUpdateBody {
  /** Scenario */
  scenario: Record<string, any>;
}

/** ScrcpyAttachRequest */
export interface ScrcpyAttachRequest {
  /** Device Ip */
  device_ip: string;
  /**
   * Adb Port
   * @default 5555
   */
  adb_port?: number;
}

/** ScrollRequest */
export interface ScrollRequest {
  /**
   * Direction
   * @default "down"
   */
  direction?: string;
  /**
   * Distance
   * @default 0.5
   */
  distance?: number;
}

/** SessionOut */
export interface SessionOut {
  /** Id */
  id: string;
  /** Client Ip */
  client_ip: string;
  /**
   * Connected At
   * @format date-time
   */
  connected_at: string;
  /** Disconnected At */
  disconnected_at: string | null;
}

/** StartSessionRequest */
export interface StartSessionRequest {
  /** Device Id */
  device_id: string;
  /** User Id */
  user_id?: string | null;
}

/** StatusUpdate */
export interface StatusUpdate {
  /** Status */
  status: string;
}

/** SwipeRequest */
export interface SwipeRequest {
  /** X1 */
  x1: number;
  /** Y1 */
  y1: number;
  /** X2 */
  x2: number;
  /** Y2 */
  y2: number;
  /**
   * Ms
   * @default 300
   */
  ms?: number;
}

/** TapRequest */
export interface TapRequest {
  /** X */
  x: number;
  /** Y */
  y: number;
}

/** TapSelectorRequest */
export interface TapSelectorRequest {
  /** By */
  by: string;
  /** Value */
  value: string;
}

/** TaskRequest */
export interface TaskRequest {
  /**
   * Fn Name
   * @default "example"
   */
  fn_name?: string;
  /**
   * Priority
   * @default 5
   */
  priority?: number;
  /** Target */
  target?: string | null;
  /**
   * Timeout
   * @default 300
   */
  timeout?: number;
  /**
   * Max Retries
   * @default 2
   */
  max_retries?: number;
}

/** TokenResponse */
export interface TokenResponse {
  /** Access Token */
  access_token: string;
  /** Refresh Token */
  refresh_token: string;
  /**
   * Token Type
   * @default "bearer"
   */
  token_type?: string;
}

/** UserCreate */
export interface UserCreate {
  /** Email */
  email: string;
  /** Name */
  name: string;
  /** Password */
  password: string;
  /**
   * Role
   * @default "operator"
   */
  role?: string;
}

/** ValidationError */
export interface ValidationError {
  /** Location */
  loc: (string | number)[];
  /** Message */
  msg: string;
  /** Error Type */
  type: string;
  /** Input */
  input?: any;
  /** Context */
  ctx?: object;
}

/** UserOut */
export interface ApiSchemasAuthUserOut {
  /** Id */
  id: string;
  /** Email */
  email: string;
  /** Name */
  name: string;
  /** Role */
  role: string;
  /** Api Key */
  api_key: string;
}

/** UserOut */
export interface ApiSchemasUserUserOut {
  /** Id */
  id: string;
  /** Email */
  email: string;
  /** Name */
  name: string;
  /** Role */
  role: string;
  /** Api Key */
  api_key: string;
  /** Is Active */
  is_active: boolean;
  /**
   * Created At
   * @format date-time
   */
  created_at: string;
}

import type {
  AxiosInstance,
  AxiosRequestConfig,
  AxiosResponse,
  HeadersDefaults,
  ResponseType,
} from "axios";
import axios from "axios";

export type QueryParamsType = Record<string | number, any>;

export interface FullRequestParams
  extends Omit<AxiosRequestConfig, "data" | "params" | "url" | "responseType"> {
  /** set parameter to `true` for call `securityWorker` for this request */
  secure?: boolean;
  /** request path */
  path: string;
  /** content type of request body */
  type?: ContentType;
  /** query params */
  query?: QueryParamsType;
  /** format of response (i.e. response.json() -> format: "json") */
  format?: ResponseType;
  /** request body */
  body?: unknown;
}

export type RequestParams = Omit<
  FullRequestParams,
  "body" | "method" | "query" | "path"
>;

export interface ApiConfig<SecurityDataType = unknown>
  extends Omit<AxiosRequestConfig, "data" | "cancelToken"> {
  securityWorker?: (
    securityData: SecurityDataType | null,
  ) => Promise<AxiosRequestConfig | void> | AxiosRequestConfig | void;
  secure?: boolean;
  format?: ResponseType;
}

export enum ContentType {
  Json = "application/json",
  JsonApi = "application/vnd.api+json",
  FormData = "multipart/form-data",
  UrlEncoded = "application/x-www-form-urlencoded",
  Text = "text/plain",
}

export class HttpClient<SecurityDataType = unknown> {
  public instance: AxiosInstance;
  private securityData: SecurityDataType | null = null;
  private securityWorker?: ApiConfig<SecurityDataType>["securityWorker"];
  private secure?: boolean;
  private format?: ResponseType;

  constructor({
    securityWorker,
    secure,
    format,
    ...axiosConfig
  }: ApiConfig<SecurityDataType> = {}) {
    this.instance = axios.create({
      ...axiosConfig,
      baseURL: axiosConfig.baseURL || "",
    });
    this.secure = secure;
    this.format = format;
    this.securityWorker = securityWorker;
  }

  public setSecurityData = (data: SecurityDataType | null) => {
    this.securityData = data;
  };

  protected mergeRequestParams(
    params1: AxiosRequestConfig,
    params2?: AxiosRequestConfig,
  ): AxiosRequestConfig {
    const method = params1.method || (params2 && params2.method);

    return {
      ...this.instance.defaults,
      ...params1,
      ...(params2 || {}),
      headers: {
        ...((method &&
          this.instance.defaults.headers[
            method.toLowerCase() as keyof HeadersDefaults
          ]) ||
          {}),
        ...(params1.headers || {}),
        ...((params2 && params2.headers) || {}),
      },
    };
  }

  protected stringifyFormItem(formItem: unknown) {
    if (typeof formItem === "object" && formItem !== null) {
      return JSON.stringify(formItem);
    } else {
      return `${formItem}`;
    }
  }

  protected createFormData(input: Record<string, unknown>): FormData {
    if (input instanceof FormData) {
      return input;
    }
    return Object.keys(input || {}).reduce((formData, key) => {
      const property = input[key];
      const propertyContent: any[] =
        property instanceof Array ? property : [property];

      for (const formItem of propertyContent) {
        const isFileType = formItem instanceof Blob || formItem instanceof File;
        formData.append(
          key,
          isFileType ? formItem : this.stringifyFormItem(formItem),
        );
      }

      return formData;
    }, new FormData());
  }

  public request = async <T = any, _E = any>({
    secure,
    path,
    type,
    query,
    format,
    body,
    ...params
  }: FullRequestParams): Promise<AxiosResponse<T>> => {
    const secureParams =
      ((typeof secure === "boolean" ? secure : this.secure) &&
        this.securityWorker &&
        (await this.securityWorker(this.securityData))) ||
      {};
    const requestParams = this.mergeRequestParams(params, secureParams);
    const responseFormat = format || this.format || undefined;

    if (
      type === ContentType.FormData &&
      body &&
      body !== null &&
      typeof body === "object"
    ) {
      body = this.createFormData(body as Record<string, unknown>);
    }

    if (
      type === ContentType.Text &&
      body &&
      body !== null &&
      typeof body !== "string"
    ) {
      body = JSON.stringify(body);
    }

    return this.instance.request({
      ...requestParams,
      headers: {
        ...(requestParams.headers || {}),
        ...(type ? { "Content-Type": type } : {}),
      },
      params: query,
      responseType: responseFormat,
      data: body,
      url: path,
    });
  };
}

/**
 * @title Android Device Farm
 * @version 2.0.0
 */
export class DeviceFarmHttpClient<
  SecurityDataType extends unknown,
> extends HttpClient<SecurityDataType> {
  /**
   * No description
   *
   * @name DashboardGet
   * @summary Dashboard
   * @request GET:/
   */
  dashboardGet = (params: RequestParams = {}) =>
    this.request<string, any>({
      path: `/`,
      method: "GET",
      ...params,
    });

  ping = {
    /**
     * No description
     *
     * @name PingPingGet
     * @summary Ping
     * @request GET:/ping
     */
    pingPingGet: (params: RequestParams = {}) =>
      this.request<any, any>({
        path: `/ping`,
        method: "GET",
        format: "json",
        ...params,
      }),
  };
  api = {
    /**
     * No description
     *
     * @name ApiDevicesLiveApiDevicesLiveGet
     * @summary Api Devices Live
     * @request GET:/api/devices/live
     */
    apiDevicesLiveApiDevicesLiveGet: (
      query?: {
        /** State */
        state?: string | null;
        /** Model */
        model?: string | null;
        /** Limit */
        limit?: number | null;
        /**
         * Offset
         * @default 0
         */
        offset?: number;
      },
      params: RequestParams = {},
    ) =>
      this.request<any, HTTPValidationError>({
        path: `/api/devices/live`,
        method: "GET",
        query: query,
        format: "json",
        ...params,
      }),

    /**
     * No description
     *
     * @name ApiConfigApiConfigGet
     * @summary Api Config
     * @request GET:/api/config
     */
    apiConfigApiConfigGet: (params: RequestParams = {}) =>
      this.request<any, any>({
        path: `/api/config`,
        method: "GET",
        format: "json",
        ...params,
      }),

    /**
     * No description
     *
     * @name ApiTasksApiTasksGet
     * @summary Api Tasks
     * @request GET:/api/tasks
     */
    apiTasksApiTasksGet: (
      query?: {
        /** Ids */
        ids?: string | null;
        /** Name Prefix */
        name_prefix?: string | null;
      },
      params: RequestParams = {},
    ) =>
      this.request<any, HTTPValidationError>({
        path: `/api/tasks`,
        method: "GET",
        query: query,
        format: "json",
        ...params,
      }),

    /**
     * No description
     *
     * @tags auth
     * @name RegisterApiAuthRegisterPost
     * @summary Register
     * @request POST:/api/auth/register
     */
    registerApiAuthRegisterPost: (
      data: RegisterRequest,
      params: RequestParams = {},
    ) =>
      this.request<ApiSchemasAuthUserOut, HTTPValidationError>({
        path: `/api/auth/register`,
        method: "POST",
        body: data,
        type: ContentType.Json,
        format: "json",
        ...params,
      }),

    /**
     * No description
     *
     * @tags auth
     * @name LoginApiAuthLoginPost
     * @summary Login
     * @request POST:/api/auth/login
     */
    loginApiAuthLoginPost: (data: LoginRequest, params: RequestParams = {}) =>
      this.request<TokenResponse, HTTPValidationError>({
        path: `/api/auth/login`,
        method: "POST",
        body: data,
        type: ContentType.Json,
        format: "json",
        ...params,
      }),

    /**
     * No description
     *
     * @tags auth
     * @name RefreshApiAuthRefreshPost
     * @summary Refresh
     * @request POST:/api/auth/refresh
     */
    refreshApiAuthRefreshPost: (
      data: RefreshRequest,
      params: RequestParams = {},
    ) =>
      this.request<TokenResponse, HTTPValidationError>({
        path: `/api/auth/refresh`,
        method: "POST",
        body: data,
        type: ContentType.Json,
        format: "json",
        ...params,
      }),

    /**
     * No description
     *
     * @tags auth
     * @name MeApiAuthMeGet
     * @summary Me
     * @request GET:/api/auth/me
     * @secure
     */
    meApiAuthMeGet: (params: RequestParams = {}) =>
      this.request<ApiSchemasAuthUserOut, any>({
        path: `/api/auth/me`,
        method: "GET",
        secure: true,
        format: "json",
        ...params,
      }),

    /**
     * @description Serve the STFService.apk used by Android devices. The file is resolved from a small set of well-known locations: - device_farm/bundle/apks/STFService.apk                (download_bundle.py output) - ../STFService.apk/app/build/outputs/apk/release/...   (local Gradle build)
     *
     * @tags devices
     * @name DownloadStfApkApiDevicesStfApkGet
     * @summary Download STFService APK
     * @request GET:/api/devices/stf-apk
     */
    downloadStfApkApiDevicesStfApkGet: (params: RequestParams = {}) =>
      this.request<any, any>({
        path: `/api/devices/stf-apk`,
        method: "GET",
        format: "json",
        ...params,
      }),

    /**
     * @description Backend chủ động kết nối tới thiết bị qua ADB over TCP. Thiết bị cần bật ADB over TCP (Wireless debugging hoặc adb tcpip 5555). Không cần QR: chỉ cần nhập IP và bấm Kết nối.
     *
     * @tags devices
     * @name ConnectDeviceByIpApiDevicesConnectAdbPost
     * @summary Connect Device By Ip
     * @request POST:/api/devices/connect-adb
     * @secure
     */
    connectDeviceByIpApiDevicesConnectAdbPost: (
      data: ConnectByIpBody,
      params: RequestParams = {},
    ) =>
      this.request<any, HTTPValidationError>({
        path: `/api/devices/connect-adb`,
        method: "POST",
        body: data,
        secure: true,
        type: ContentType.Json,
        format: "json",
        ...params,
      }),

    /**
     * @description Đăng ký thiết bị: chỉ tạo bản ghi (serial = pending-xxx), chưa kết nối điện thoại. Để kết nối điện thoại thật, user vào thẻ thiết bị → nhấn Kết nối → quét mã QR (key=device_key).
     *
     * @tags devices
     * @name RegisterDeviceApiDevicesRegisterPost
     * @summary Register Device
     * @request POST:/api/devices/register
     * @secure
     */
    registerDeviceApiDevicesRegisterPost: (
      data: RegisterDeviceBody,
      params: RequestParams = {},
    ) =>
      this.request<DeviceOut, HTTPValidationError>({
        path: `/api/devices/register`,
        method: "POST",
        body: data,
        secure: true,
        type: ContentType.Json,
        format: "json",
        ...params,
      }),

    /**
     * No description
     *
     * @tags devices
     * @name CreatePairingApiDevicesPairPost
     * @summary Create Pairing
     * @request POST:/api/devices/pair
     * @secure
     */
    createPairingApiDevicesPairPost: (params: RequestParams = {}) =>
      this.request<any, any>({
        path: `/api/devices/pair`,
        method: "POST",
        secure: true,
        format: "json",
        ...params,
      }),

    /**
     * @description Tạo nhiều pairing cùng lúc để kết nối nhiều thiết bị. Mỗi thiết bị dùng một URL (copy hoặc quét QR).
     *
     * @tags devices
     * @name CreatePairingBulkApiDevicesPairBulkPost
     * @summary Create Pairing Bulk
     * @request POST:/api/devices/pair/bulk
     * @secure
     */
    createPairingBulkApiDevicesPairBulkPost: (
      data: PairBulkBody,
      params: RequestParams = {},
    ) =>
      this.request<any, HTTPValidationError>({
        path: `/api/devices/pair/bulk`,
        method: "POST",
        body: data,
        secure: true,
        type: ContentType.Json,
        format: "json",
        ...params,
      }),

    /**
     * @description Poll until device connects and pairing is complete.
     *
     * @tags devices
     * @name PollPairingApiDevicesPairPairingIdGet
     * @summary Poll Pairing
     * @request GET:/api/devices/pair/{pairing_id}
     * @secure
     */
    pollPairingApiDevicesPairPairingIdGet: (
      pairingId: string,
      params: RequestParams = {},
    ) =>
      this.request<any, HTTPValidationError>({
        path: `/api/devices/pair/${pairingId}`,
        method: "GET",
        secure: true,
        format: "json",
        ...params,
      }),

    /**
     * No description
     *
     * @tags devices
     * @name ListDevicesApiDevicesGet
     * @summary List Devices
     * @request GET:/api/devices
     * @secure
     */
    listDevicesApiDevicesGet: (params: RequestParams = {}) =>
      this.request<DeviceOut[], any>({
        path: `/api/devices`,
        method: "GET",
        secure: true,
        format: "json",
        ...params,
      }),

    /**
     * @description Đăng ký thiết bị thủ công bằng serial (dùng cho script/admin). Đăng ký từ UI phải qua POST /pair + quét mã QR, không dùng endpoint này. Semantics: - If no device with this serial exists: create and assign to current user. - If it exists without an owner (user_id is NULL): claim it for current user. - If it already belongs to current user: idempotent (optionally updates name). - If it belongs to another user: 409.
     *
     * @tags devices
     * @name CreateDeviceApiDevicesPost
     * @summary Create Device
     * @request POST:/api/devices
     * @secure
     */
    createDeviceApiDevicesPost: (
      data: DeviceCreate,
      params: RequestParams = {},
    ) =>
      this.request<DeviceOut, HTTPValidationError>({
        path: `/api/devices`,
        method: "POST",
        body: data,
        secure: true,
        type: ContentType.Json,
        format: "json",
        ...params,
      }),

    /**
     * No description
     *
     * @tags devices
     * @name GetDeviceApiDevicesDeviceIdGet
     * @summary Get Device
     * @request GET:/api/devices/{device_id}
     * @secure
     */
    getDeviceApiDevicesDeviceIdGet: (
      deviceId: string,
      params: RequestParams = {},
    ) =>
      this.request<DeviceOut, HTTPValidationError>({
        path: `/api/devices/${deviceId}`,
        method: "GET",
        secure: true,
        format: "json",
        ...params,
      }),

    /**
     * @description Xoá thiết bị của user hiện tại và mọi liên kết campaign-device.
     *
     * @tags devices
     * @name DeleteDeviceApiDevicesDeviceIdDelete
     * @summary Delete Device
     * @request DELETE:/api/devices/{device_id}
     * @secure
     */
    deleteDeviceApiDevicesDeviceIdDelete: (
      deviceId: string,
      params: RequestParams = {},
    ) =>
      this.request<void, HTTPValidationError>({
        path: `/api/devices/${deviceId}`,
        method: "DELETE",
        secure: true,
        ...params,
      }),

    /**
     * No description
     *
     * @tags devices
     * @name DeviceSessionsApiDevicesDeviceIdSessionsGet
     * @summary Device Sessions
     * @request GET:/api/devices/{device_id}/sessions
     * @secure
     */
    deviceSessionsApiDevicesDeviceIdSessionsGet: (
      deviceId: string,
      params: RequestParams = {},
    ) =>
      this.request<SessionOut[], HTTPValidationError>({
        path: `/api/devices/${deviceId}/sessions`,
        method: "GET",
        secure: true,
        format: "json",
        ...params,
      }),

    /**
     * No description
     *
     * @tags users
     * @name ListUsersApiUsersGet
     * @summary List Users
     * @request GET:/api/users
     * @secure
     */
    listUsersApiUsersGet: (params: RequestParams = {}) =>
      this.request<ApiSchemasUserUserOut[], any>({
        path: `/api/users`,
        method: "GET",
        secure: true,
        format: "json",
        ...params,
      }),

    /**
     * No description
     *
     * @tags users
     * @name CreateUserApiUsersPost
     * @summary Create User
     * @request POST:/api/users
     * @secure
     */
    createUserApiUsersPost: (data: UserCreate, params: RequestParams = {}) =>
      this.request<ApiSchemasUserUserOut, HTTPValidationError>({
        path: `/api/users`,
        method: "POST",
        body: data,
        secure: true,
        type: ContentType.Json,
        format: "json",
        ...params,
      }),

    /**
     * No description
     *
     * @tags users
     * @name GetUserApiUsersUserIdGet
     * @summary Get User
     * @request GET:/api/users/{user_id}
     * @secure
     */
    getUserApiUsersUserIdGet: (userId: string, params: RequestParams = {}) =>
      this.request<ApiSchemasUserUserOut, HTTPValidationError>({
        path: `/api/users/${userId}`,
        method: "GET",
        secure: true,
        format: "json",
        ...params,
      }),

    /**
     * No description
     *
     * @tags campaigns
     * @name ListCampaignsApiCampaignsGet
     * @summary List Campaigns
     * @request GET:/api/campaigns
     * @secure
     */
    listCampaignsApiCampaignsGet: (params: RequestParams = {}) =>
      this.request<CampaignOut[], any>({
        path: `/api/campaigns`,
        method: "GET",
        secure: true,
        format: "json",
        ...params,
      }),

    /**
     * No description
     *
     * @tags campaigns
     * @name CreateCampaignApiCampaignsPost
     * @summary Create Campaign
     * @request POST:/api/campaigns
     * @secure
     */
    createCampaignApiCampaignsPost: (
      data: CampaignCreate,
      params: RequestParams = {},
    ) =>
      this.request<CampaignOut, HTTPValidationError>({
        path: `/api/campaigns`,
        method: "POST",
        body: data,
        secure: true,
        type: ContentType.Json,
        format: "json",
        ...params,
      }),

    /**
     * No description
     *
     * @tags campaigns
     * @name GetCampaignApiCampaignsCampaignIdGet
     * @summary Get Campaign
     * @request GET:/api/campaigns/{campaign_id}
     * @secure
     */
    getCampaignApiCampaignsCampaignIdGet: (
      campaignId: string,
      params: RequestParams = {},
    ) =>
      this.request<CampaignOut, HTTPValidationError>({
        path: `/api/campaigns/${campaignId}`,
        method: "GET",
        secure: true,
        format: "json",
        ...params,
      }),

    /**
     * No description
     *
     * @tags campaigns
     * @name DeleteCampaignApiCampaignsCampaignIdDelete
     * @summary Delete Campaign
     * @request DELETE:/api/campaigns/{campaign_id}
     * @secure
     */
    deleteCampaignApiCampaignsCampaignIdDelete: (
      campaignId: string,
      params: RequestParams = {},
    ) =>
      this.request<void, HTTPValidationError>({
        path: `/api/campaigns/${campaignId}`,
        method: "DELETE",
        secure: true,
        ...params,
      }),

    /**
     * No description
     *
     * @tags campaigns
     * @name UpdateStatusApiCampaignsCampaignIdStatusPatch
     * @summary Update Status
     * @request PATCH:/api/campaigns/{campaign_id}/status
     * @secure
     */
    updateStatusApiCampaignsCampaignIdStatusPatch: (
      campaignId: string,
      data: StatusUpdate,
      params: RequestParams = {},
    ) =>
      this.request<any, HTTPValidationError>({
        path: `/api/campaigns/${campaignId}/status`,
        method: "PATCH",
        body: data,
        secure: true,
        type: ContentType.Json,
        format: "json",
        ...params,
      }),

    /**
     * No description
     *
     * @tags campaigns
     * @name CampaignDevicesApiCampaignsCampaignIdDevicesGet
     * @summary Campaign Devices
     * @request GET:/api/campaigns/{campaign_id}/devices
     * @secure
     */
    campaignDevicesApiCampaignsCampaignIdDevicesGet: (
      campaignId: string,
      params: RequestParams = {},
    ) =>
      this.request<CampaignDeviceOut[], HTTPValidationError>({
        path: `/api/campaigns/${campaignId}/devices`,
        method: "GET",
        secure: true,
        format: "json",
        ...params,
      }),

    /**
     * No description
     *
     * @tags campaigns
     * @name AddDeviceApiCampaignsCampaignIdDevicesPost
     * @summary Add Device
     * @request POST:/api/campaigns/{campaign_id}/devices
     * @secure
     */
    addDeviceApiCampaignsCampaignIdDevicesPost: (
      campaignId: string,
      data: AddDeviceBody,
      params: RequestParams = {},
    ) =>
      this.request<any, HTTPValidationError>({
        path: `/api/campaigns/${campaignId}/devices`,
        method: "POST",
        body: data,
        secure: true,
        type: ContentType.Json,
        format: "json",
        ...params,
      }),

    /**
     * No description
     *
     * @tags campaigns
     * @name RemoveDeviceApiCampaignsCampaignIdDevicesDeviceIdDelete
     * @summary Remove Device
     * @request DELETE:/api/campaigns/{campaign_id}/devices/{device_id}
     * @secure
     */
    removeDeviceApiCampaignsCampaignIdDevicesDeviceIdDelete: (
      campaignId: string,
      deviceId: string,
      params: RequestParams = {},
    ) =>
      this.request<any, HTTPValidationError>({
        path: `/api/campaigns/${campaignId}/devices/${deviceId}`,
        method: "DELETE",
        secure: true,
        format: "json",
        ...params,
      }),

    /**
     * No description
     *
     * @tags campaigns
     * @name UpdateScenarioApiCampaignsCampaignIdScenarioPatch
     * @summary Update Scenario
     * @request PATCH:/api/campaigns/{campaign_id}/scenario
     * @secure
     */
    updateScenarioApiCampaignsCampaignIdScenarioPatch: (
      campaignId: string,
      data: ScenarioUpdateBody,
      params: RequestParams = {},
    ) =>
      this.request<CampaignOut, HTTPValidationError>({
        path: `/api/campaigns/${campaignId}/scenario`,
        method: "PATCH",
        body: data,
        secure: true,
        type: ContentType.Json,
        format: "json",
        ...params,
      }),

    /**
     * No description
     *
     * @tags campaigns
     * @name CompileScenarioApiCampaignsCampaignIdCompileScenarioPost
     * @summary Compile Scenario
     * @request POST:/api/campaigns/{campaign_id}/compile-scenario
     * @secure
     */
    compileScenarioApiCampaignsCampaignIdCompileScenarioPost: (
      campaignId: string,
      data: CompileScenarioBody,
      params: RequestParams = {},
    ) =>
      this.request<CampaignOut, HTTPValidationError>({
        path: `/api/campaigns/${campaignId}/compile-scenario`,
        method: "POST",
        body: data,
        secure: true,
        type: ContentType.Json,
        format: "json",
        ...params,
      }),

    /**
     * No description
     *
     * @tags campaigns
     * @name ListScenariosApiCampaignsCampaignIdScenariosGet
     * @summary List Scenarios
     * @request GET:/api/campaigns/{campaign_id}/scenarios
     * @secure
     */
    listScenariosApiCampaignsCampaignIdScenariosGet: (
      campaignId: string,
      params: RequestParams = {},
    ) =>
      this.request<ScenarioOut[], HTTPValidationError>({
        path: `/api/campaigns/${campaignId}/scenarios`,
        method: "GET",
        secure: true,
        format: "json",
        ...params,
      }),

    /**
     * No description
     *
     * @tags campaigns
     * @name CreateScenarioApiCampaignsCampaignIdScenariosPost
     * @summary Create Scenario
     * @request POST:/api/campaigns/{campaign_id}/scenarios
     * @secure
     */
    createScenarioApiCampaignsCampaignIdScenariosPost: (
      campaignId: string,
      data: ScenarioCreate,
      params: RequestParams = {},
    ) =>
      this.request<ScenarioOut, HTTPValidationError>({
        path: `/api/campaigns/${campaignId}/scenarios`,
        method: "POST",
        body: data,
        secure: true,
        type: ContentType.Json,
        format: "json",
        ...params,
      }),

    /**
     * No description
     *
     * @tags campaigns
     * @name GetScenarioApiCampaignsCampaignIdScenariosScenarioIdGet
     * @summary Get Scenario
     * @request GET:/api/campaigns/{campaign_id}/scenarios/{scenario_id}
     * @secure
     */
    getScenarioApiCampaignsCampaignIdScenariosScenarioIdGet: (
      campaignId: string,
      scenarioId: string,
      params: RequestParams = {},
    ) =>
      this.request<ScenarioOut, HTTPValidationError>({
        path: `/api/campaigns/${campaignId}/scenarios/${scenarioId}`,
        method: "GET",
        secure: true,
        format: "json",
        ...params,
      }),

    /**
     * No description
     *
     * @tags campaigns
     * @name UpdateScenarioRouteApiCampaignsCampaignIdScenariosScenarioIdPatch
     * @summary Update Scenario Route
     * @request PATCH:/api/campaigns/{campaign_id}/scenarios/{scenario_id}
     * @secure
     */
    updateScenarioRouteApiCampaignsCampaignIdScenariosScenarioIdPatch: (
      campaignId: string,
      scenarioId: string,
      data: ScenarioUpdate,
      params: RequestParams = {},
    ) =>
      this.request<ScenarioOut, HTTPValidationError>({
        path: `/api/campaigns/${campaignId}/scenarios/${scenarioId}`,
        method: "PATCH",
        body: data,
        secure: true,
        type: ContentType.Json,
        format: "json",
        ...params,
      }),

    /**
     * No description
     *
     * @tags campaigns
     * @name DeleteScenarioRouteApiCampaignsCampaignIdScenariosScenarioIdDelete
     * @summary Delete Scenario Route
     * @request DELETE:/api/campaigns/{campaign_id}/scenarios/{scenario_id}
     * @secure
     */
    deleteScenarioRouteApiCampaignsCampaignIdScenariosScenarioIdDelete: (
      campaignId: string,
      scenarioId: string,
      params: RequestParams = {},
    ) =>
      this.request<void, HTTPValidationError>({
        path: `/api/campaigns/${campaignId}/scenarios/${scenarioId}`,
        method: "DELETE",
        secure: true,
        ...params,
      }),

    /**
     * No description
     *
     * @tags campaigns
     * @name CompileScenarioRowApiCampaignsCampaignIdScenariosScenarioIdCompilePost
     * @summary Compile Scenario Row
     * @request POST:/api/campaigns/{campaign_id}/scenarios/{scenario_id}/compile
     * @secure
     */
    compileScenarioRowApiCampaignsCampaignIdScenariosScenarioIdCompilePost: (
      campaignId: string,
      scenarioId: string,
      data: CompileScenarioBody,
      params: RequestParams = {},
    ) =>
      this.request<ScenarioOut, HTTPValidationError>({
        path: `/api/campaigns/${campaignId}/scenarios/${scenarioId}/compile`,
        method: "POST",
        body: data,
        secure: true,
        type: ContentType.Json,
        format: "json",
        ...params,
      }),

    /**
     * No description
     *
     * @tags organizations
     * @name ListMyOrganizationsApiOrganizationsGet
     * @summary List My Organizations
     * @request GET:/api/organizations
     * @secure
     */
    listMyOrganizationsApiOrganizationsGet: (params: RequestParams = {}) =>
      this.request<OrganizationOut[], any>({
        path: `/api/organizations`,
        method: "GET",
        secure: true,
        format: "json",
        ...params,
      }),

    /**
     * No description
     *
     * @tags organizations
     * @name CreateOrganizationApiOrganizationsPost
     * @summary Create Organization
     * @request POST:/api/organizations
     * @secure
     */
    createOrganizationApiOrganizationsPost: (
      data: OrganizationCreate,
      params: RequestParams = {},
    ) =>
      this.request<OrganizationOut, HTTPValidationError>({
        path: `/api/organizations`,
        method: "POST",
        body: data,
        secure: true,
        type: ContentType.Json,
        format: "json",
        ...params,
      }),

    /**
     * No description
     *
     * @tags device-control
     * @name ApiConnectInfoApiConnectInfoGet
     * @summary Api Connect Info
     * @request GET:/api/connect/info
     */
    apiConnectInfoApiConnectInfoGet: (params: RequestParams = {}) =>
      this.request<any, any>({
        path: `/api/connect/info`,
        method: "GET",
        format: "json",
        ...params,
      }),

    /**
     * No description
     *
     * @tags device-control
     * @name ApiScenarioSchemaApiScenarioSchemaGet
     * @summary Api Scenario Schema
     * @request GET:/api/scenario/schema
     */
    apiScenarioSchemaApiScenarioSchemaGet: (params: RequestParams = {}) =>
      this.request<any, any>({
        path: `/api/scenario/schema`,
        method: "GET",
        format: "json",
        ...params,
      }),

    /**
     * No description
     *
     * @tags device-control
     * @name ApiConnectRegisterApiConnectRegisterPost
     * @summary Api Connect Register
     * @request POST:/api/connect/register
     */
    apiConnectRegisterApiConnectRegisterPost: (
      data: AdbRegisterRequest,
      params: RequestParams = {},
    ) =>
      this.request<any, HTTPValidationError>({
        path: `/api/connect/register`,
        method: "POST",
        body: data,
        type: ContentType.Json,
        format: "json",
        ...params,
      }),

    /**
     * No description
     *
     * @tags device-control
     * @name ApiScrcpyAttachApiDevicesSerialScrcpyAttachPost
     * @summary Api Scrcpy Attach
     * @request POST:/api/devices/{serial}/scrcpy/attach
     */
    apiScrcpyAttachApiDevicesSerialScrcpyAttachPost: (
      serial: string,
      data: ScrcpyAttachRequest,
      params: RequestParams = {},
    ) =>
      this.request<any, HTTPValidationError>({
        path: `/api/devices/${serial}/scrcpy/attach`,
        method: "POST",
        body: data,
        type: ContentType.Json,
        format: "json",
        ...params,
      }),

    /**
     * No description
     *
     * @tags device-control
     * @name ApiScrcpyDetachApiDevicesSerialScrcpyDetachPost
     * @summary Api Scrcpy Detach
     * @request POST:/api/devices/{serial}/scrcpy/detach
     */
    apiScrcpyDetachApiDevicesSerialScrcpyDetachPost: (
      serial: string,
      params: RequestParams = {},
    ) =>
      this.request<any, HTTPValidationError>({
        path: `/api/devices/${serial}/scrcpy/detach`,
        method: "POST",
        format: "json",
        ...params,
      }),

    /**
     * No description
     *
     * @tags device-control
     * @name ApiSessionsStartApiSessionsStartPost
     * @summary Api Sessions Start
     * @request POST:/api/sessions/start
     */
    apiSessionsStartApiSessionsStartPost: (
      data: StartSessionRequest,
      params: RequestParams = {},
    ) =>
      this.request<any, HTTPValidationError>({
        path: `/api/sessions/start`,
        method: "POST",
        body: data,
        type: ContentType.Json,
        format: "json",
        ...params,
      }),

    /**
     * No description
     *
     * @tags device-control
     * @name ApiSessionsEndApiSessionsEndPost
     * @summary Api Sessions End
     * @request POST:/api/sessions/end
     */
    apiSessionsEndApiSessionsEndPost: (
      data: EndSessionRequest,
      params: RequestParams = {},
    ) =>
      this.request<any, HTTPValidationError>({
        path: `/api/sessions/end`,
        method: "POST",
        body: data,
        type: ContentType.Json,
        format: "json",
        ...params,
      }),

    /**
     * No description
     *
     * @tags device-control
     * @name ApiSessionsGetApiSessionsSessionIdGet
     * @summary Api Sessions Get
     * @request GET:/api/sessions/{session_id}
     */
    apiSessionsGetApiSessionsSessionIdGet: (
      sessionId: string,
      params: RequestParams = {},
    ) =>
      this.request<any, HTTPValidationError>({
        path: `/api/sessions/${sessionId}`,
        method: "GET",
        format: "json",
        ...params,
      }),

    /**
     * No description
     *
     * @tags device-control
     * @name ApiDevicesReserveApiDevicesSerialReservePost
     * @summary Api Devices Reserve
     * @request POST:/api/devices/{serial}/reserve
     */
    apiDevicesReserveApiDevicesSerialReservePost: (
      serial: string,
      params: RequestParams = {},
    ) =>
      this.request<any, HTTPValidationError>({
        path: `/api/devices/${serial}/reserve`,
        method: "POST",
        format: "json",
        ...params,
      }),

    /**
     * No description
     *
     * @tags device-control
     * @name ApiDevicesReleaseApiDevicesSerialReleasePost
     * @summary Api Devices Release
     * @request POST:/api/devices/{serial}/release
     */
    apiDevicesReleaseApiDevicesSerialReleasePost: (
      serial: string,
      params: RequestParams = {},
    ) =>
      this.request<any, HTTPValidationError>({
        path: `/api/devices/${serial}/release`,
        method: "POST",
        format: "json",
        ...params,
      }),

    /**
     * No description
     *
     * @tags device-control
     * @name ApiTapApiTapSerialPost
     * @summary Api Tap
     * @request POST:/api/tap/{serial}
     */
    apiTapApiTapSerialPost: (
      serial: string,
      data: TapRequest,
      params: RequestParams = {},
    ) =>
      this.request<any, HTTPValidationError>({
        path: `/api/tap/${serial}`,
        method: "POST",
        body: data,
        type: ContentType.Json,
        format: "json",
        ...params,
      }),

    /**
     * No description
     *
     * @tags device-control
     * @name ApiSwipeApiSwipeSerialPost
     * @summary Api Swipe
     * @request POST:/api/swipe/{serial}
     */
    apiSwipeApiSwipeSerialPost: (
      serial: string,
      data: SwipeRequest,
      params: RequestParams = {},
    ) =>
      this.request<any, HTTPValidationError>({
        path: `/api/swipe/${serial}`,
        method: "POST",
        body: data,
        type: ContentType.Json,
        format: "json",
        ...params,
      }),

    /**
     * No description
     *
     * @tags device-control
     * @name ApiKeyApiKeySerialPost
     * @summary Api Key
     * @request POST:/api/key/{serial}
     */
    apiKeyApiKeySerialPost: (
      serial: string,
      data: KeyRequest,
      params: RequestParams = {},
    ) =>
      this.request<any, HTTPValidationError>({
        path: `/api/key/${serial}`,
        method: "POST",
        body: data,
        type: ContentType.Json,
        format: "json",
        ...params,
      }),

    /**
     * No description
     *
     * @tags device-control
     * @name ApiOpenUrlApiOpenUrlSerialPost
     * @summary Api Open Url
     * @request POST:/api/open_url/{serial}
     */
    apiOpenUrlApiOpenUrlSerialPost: (
      serial: string,
      data: OpenUrlRequest,
      params: RequestParams = {},
    ) =>
      this.request<any, HTTPValidationError>({
        path: `/api/open_url/${serial}`,
        method: "POST",
        body: data,
        type: ContentType.Json,
        format: "json",
        ...params,
      }),

    /**
     * No description
     *
     * @tags device-control
     * @name ApiInputTextApiDevicesSerialInputTextPost
     * @summary Api Input Text
     * @request POST:/api/devices/{serial}/input_text
     */
    apiInputTextApiDevicesSerialInputTextPost: (
      serial: string,
      data: InputTextRequest,
      params: RequestParams = {},
    ) =>
      this.request<any, HTTPValidationError>({
        path: `/api/devices/${serial}/input_text`,
        method: "POST",
        body: data,
        type: ContentType.Json,
        format: "json",
        ...params,
      }),

    /**
     * No description
     *
     * @tags device-control
     * @name ApiLongTapApiDevicesSerialLongTapPost
     * @summary Api Long Tap
     * @request POST:/api/devices/{serial}/long_tap
     */
    apiLongTapApiDevicesSerialLongTapPost: (
      serial: string,
      data: LongTapRequest,
      params: RequestParams = {},
    ) =>
      this.request<any, HTTPValidationError>({
        path: `/api/devices/${serial}/long_tap`,
        method: "POST",
        body: data,
        type: ContentType.Json,
        format: "json",
        ...params,
      }),

    /**
     * No description
     *
     * @tags device-control
     * @name ApiScrollApiDevicesSerialScrollPost
     * @summary Api Scroll
     * @request POST:/api/devices/{serial}/scroll
     */
    apiScrollApiDevicesSerialScrollPost: (
      serial: string,
      data: ScrollRequest,
      params: RequestParams = {},
    ) =>
      this.request<any, HTTPValidationError>({
        path: `/api/devices/${serial}/scroll`,
        method: "POST",
        body: data,
        type: ContentType.Json,
        format: "json",
        ...params,
      }),

    /**
     * No description
     *
     * @tags device-control
     * @name ApiHierarchyApiDevicesSerialHierarchyGet
     * @summary Api Hierarchy
     * @request GET:/api/devices/{serial}/hierarchy
     */
    apiHierarchyApiDevicesSerialHierarchyGet: (
      serial: string,
      query?: {
        /**
         * Refresh
         * @default false
         */
        refresh?: boolean;
      },
      params: RequestParams = {},
    ) =>
      this.request<any, HTTPValidationError>({
        path: `/api/devices/${serial}/hierarchy`,
        method: "GET",
        query: query,
        format: "json",
        ...params,
      }),

    /**
     * No description
     *
     * @tags device-control
     * @name ApiUiElementsApiDevicesSerialUiElementsGet
     * @summary Api Ui Elements
     * @request GET:/api/devices/{serial}/ui_elements
     */
    apiUiElementsApiDevicesSerialUiElementsGet: (
      serial: string,
      query?: {
        /**
         * Refresh
         * @default true
         */
        refresh?: boolean;
      },
      params: RequestParams = {},
    ) =>
      this.request<any, HTTPValidationError>({
        path: `/api/devices/${serial}/ui_elements`,
        method: "GET",
        query: query,
        format: "json",
        ...params,
      }),

    /**
     * No description
     *
     * @tags device-control
     * @name ApiTapSelectorApiTapSelectorSerialPost
     * @summary Api Tap Selector
     * @request POST:/api/tap_selector/{serial}
     */
    apiTapSelectorApiTapSelectorSerialPost: (
      serial: string,
      data: TapSelectorRequest,
      params: RequestParams = {},
    ) =>
      this.request<any, HTTPValidationError>({
        path: `/api/tap_selector/${serial}`,
        method: "POST",
        body: data,
        type: ContentType.Json,
        format: "json",
        ...params,
      }),

    /**
     * No description
     *
     * @tags device-control
     * @name ApiHitTestApiDevicesSerialHitTestPost
     * @summary Api Hit Test
     * @request POST:/api/devices/{serial}/hit_test
     */
    apiHitTestApiDevicesSerialHitTestPost: (
      serial: string,
      data: HitTestRequest,
      params: RequestParams = {},
    ) =>
      this.request<any, HTTPValidationError>({
        path: `/api/devices/${serial}/hit_test`,
        method: "POST",
        body: data,
        type: ContentType.Json,
        format: "json",
        ...params,
      }),

    /**
     * No description
     *
     * @tags device-control
     * @name ApiGetTaskApiTasksTaskIdGet
     * @summary Api Get Task
     * @request GET:/api/tasks/{task_id}
     */
    apiGetTaskApiTasksTaskIdGet: (taskId: string, params: RequestParams = {}) =>
      this.request<any, HTTPValidationError>({
        path: `/api/tasks/${taskId}`,
        method: "GET",
        format: "json",
        ...params,
      }),

    /**
     * No description
     *
     * @tags device-control
     * @name ApiShellApiAgentSerialShellPost
     * @summary Api Shell
     * @request POST:/api/agent/{serial}/shell
     */
    apiShellApiAgentSerialShellPost: (
      serial: string,
      data: Record<string, any>,
      params: RequestParams = {},
    ) =>
      this.request<any, HTTPValidationError>({
        path: `/api/agent/${serial}/shell`,
        method: "POST",
        body: data,
        type: ContentType.Json,
        format: "json",
        ...params,
      }),

    /**
     * No description
     *
     * @tags device-control
     * @name ApiEnqueueTaskApiTaskPost
     * @summary Api Enqueue Task
     * @request POST:/api/task
     */
    apiEnqueueTaskApiTaskPost: (
      data: TaskRequest,
      params: RequestParams = {},
    ) =>
      this.request<any, HTTPValidationError>({
        path: `/api/task`,
        method: "POST",
        body: data,
        type: ContentType.Json,
        format: "json",
        ...params,
      }),

    /**
     * No description
     *
     * @tags device-control
     * @name ApiScenarioPreviewApiDevicesSerialScenarioPreviewPost
     * @summary Api Scenario Preview
     * @request POST:/api/devices/{serial}/scenario/preview
     */
    apiScenarioPreviewApiDevicesSerialScenarioPreviewPost: (
      serial: string,
      data: ScenarioPreviewRequest,
      params: RequestParams = {},
    ) =>
      this.request<any, HTTPValidationError>({
        path: `/api/devices/${serial}/scenario/preview`,
        method: "POST",
        body: data,
        type: ContentType.Json,
        format: "json",
        ...params,
      }),

    /**
     * No description
     *
     * @tags device-control
     * @name ApiScenarioRunApiDevicesSerialScenarioRunPost
     * @summary Api Scenario Run
     * @request POST:/api/devices/{serial}/scenario/run
     */
    apiScenarioRunApiDevicesSerialScenarioRunPost: (
      serial: string,
      data: ScenarioPreviewRequest,
      params: RequestParams = {},
    ) =>
      this.request<any, HTTPValidationError>({
        path: `/api/devices/${serial}/scenario/run`,
        method: "POST",
        body: data,
        type: ContentType.Json,
        format: "json",
        ...params,
      }),

    /**
     * No description
     *
     * @tags device-control
     * @name ApiSessionsScenarioRunApiSessionsSessionIdScenarioRunPost
     * @summary Api Sessions Scenario Run
     * @request POST:/api/sessions/{session_id}/scenario/run
     */
    apiSessionsScenarioRunApiSessionsSessionIdScenarioRunPost: (
      sessionId: string,
      data: ScenarioPreviewRequest,
      params: RequestParams = {},
    ) =>
      this.request<any, HTTPValidationError>({
        path: `/api/sessions/${sessionId}/scenario/run`,
        method: "POST",
        body: data,
        type: ContentType.Json,
        format: "json",
        ...params,
      }),

    /**
     * No description
     *
     * @tags device-control
     * @name ApiRunCampaignApiCampaignsCampaignIdRunPost
     * @summary Api Run Campaign
     * @request POST:/api/campaigns/{campaign_id}/run
     */
    apiRunCampaignApiCampaignsCampaignIdRunPost: (
      campaignId: string,
      params: RequestParams = {},
    ) =>
      this.request<any, HTTPValidationError>({
        path: `/api/campaigns/${campaignId}/run`,
        method: "POST",
        format: "json",
        ...params,
      }),

    /**
     * No description
     *
     * @tags device-control
     * @name ApiFleetRunApiFleetRunPost
     * @summary Api Fleet Run
     * @request POST:/api/fleet/run
     */
    apiFleetRunApiFleetRunPost: (
      data: FleetRunRequest,
      params: RequestParams = {},
    ) =>
      this.request<any, HTTPValidationError>({
        path: `/api/fleet/run`,
        method: "POST",
        body: data,
        type: ContentType.Json,
        format: "json",
        ...params,
      }),

    /**
     * No description
     *
     * @tags device-control
     * @name ApiFleetStatusApiFleetStatusGet
     * @summary Api Fleet Status
     * @request GET:/api/fleet/status
     */
    apiFleetStatusApiFleetStatusGet: (
      query?: {
        /** Run Id */
        run_id?: string | null;
      },
      params: RequestParams = {},
    ) =>
      this.request<any, HTTPValidationError>({
        path: `/api/fleet/status`,
        method: "GET",
        query: query,
        format: "json",
        ...params,
      }),
  };
  stream = {
    /**
     * No description
     *
     * @name MjpegStreamStreamSerialGet
     * @summary Mjpeg Stream
     * @request GET:/stream/{serial}
     */
    mjpegStreamStreamSerialGet: (serial: string, params: RequestParams = {}) =>
      this.request<any, HTTPValidationError>({
        path: `/stream/${serial}`,
        method: "GET",
        format: "json",
        ...params,
      }),
  };
  screenshot = {
    /**
     * No description
     *
     * @name ScreenshotScreenshotSerialGet
     * @summary Screenshot
     * @request GET:/screenshot/{serial}
     */
    screenshotScreenshotSerialGet: (
      serial: string,
      params: RequestParams = {},
    ) =>
      this.request<any, HTTPValidationError>({
        path: `/screenshot/${serial}`,
        method: "GET",
        format: "json",
        ...params,
      }),
  };
}
