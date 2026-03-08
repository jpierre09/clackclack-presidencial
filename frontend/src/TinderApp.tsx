import { useEffect, useState } from "react";
import { LoginPage } from "./pages/LoginPage";
import { TinderValidatePage } from "./pages/TinderValidatePage";

const TOKEN_KEY = "validate_token";
const USER_KEY = "validate_user";

export function TinderApp() {
  const [token, setToken] = useState<string | null>(() =>
    localStorage.getItem(TOKEN_KEY)
  );
  const [username, setUsername] = useState<string>(() =>
    localStorage.getItem(USER_KEY) ?? ""
  );
  const [verified, setVerified] = useState(false);

  // Verify stored token is still valid
  useEffect(() => {
    if (!token) { setVerified(true); return; }
    fetch("/api/validar/auth/me", { headers: { "X-Session-Token": token } })
      .then((r) => {
        if (!r.ok) {
          localStorage.removeItem(TOKEN_KEY);
          localStorage.removeItem(USER_KEY);
          setToken(null);
          setUsername("");
        }
        setVerified(true);
      })
      .catch(() => setVerified(true));
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  function handleLogin(t: string, u: string) {
    localStorage.setItem(TOKEN_KEY, t);
    localStorage.setItem(USER_KEY, u);
    setToken(t);
    setUsername(u);
  }

  function handleLogout() {
    if (token) {
      fetch("/api/validar/auth/logout", {
        method: "POST",
        headers: { "X-Session-Token": token },
      }).catch(() => {});
    }
    localStorage.removeItem(TOKEN_KEY);
    localStorage.removeItem(USER_KEY);
    setToken(null);
    setUsername("");
  }

  if (!verified) {
    return <div className="tinder-root"><p className="tinder-loading">Verificando sesión...</p></div>;
  }

  if (!token) {
    return <LoginPage onLogin={handleLogin} />;
  }

  return (
    <TinderValidatePage
      token={token}
      username={username}
      onLogout={handleLogout}
    />
  );
}
