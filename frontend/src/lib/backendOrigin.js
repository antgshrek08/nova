// Compare parsed origins, never string prefixes: //host and userinfo URLs
// must not inherit the credential used to control the user's computer.
export function isBackendRequest(input, backendUrl, baseUrl) {
  try {
    const target = typeof input === 'string' || input instanceof URL ? input : input?.url;
    return new URL(target, baseUrl).origin === new URL(backendUrl).origin;
  } catch {
    return false;
  }
}
