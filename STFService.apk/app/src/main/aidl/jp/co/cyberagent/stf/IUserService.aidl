package jp.co.cyberagent.stf;

/**
 * AIDL interface for the Shizuku UserService.
 * The service runs with SHELL uid, allowing it to call am instrument.
 */
interface IUserService {
    /** Required by Shizuku — called when the service should terminate. */
    void destroy();

    /**
     * Start uiautomator2 server via am instrument.
     * Runs as SHELL uid, so Permission Denial does not apply.
     * @return 0 on success, non-zero on failure.
     */
    int startUiAutomator2(String pkg);
}
