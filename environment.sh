# Sourced inside the container by both launchers. Do not put real API keys here.
# The host launcher substitutes #PORT# before copying this into container home.
[[ ${GUIX_JAIL_ENV_READY:-} == 1 ]] && return 0

# Export PATH with "exposed" pnpm install dir:
export PATH="$PATH":/host-pnpm/bin

# Set external editor:
export EDITOR="nano"
export VISUAL="nano"

# Set environment for mitmdump
export http_proxy="http://127.0.0.1:#PORT#"
export https_proxy="http://127.0.0.1:#PORT#"
export HTTP_PROXY="http://127.0.0.1:#PORT#"
export HTTPS_PROXY="http://127.0.0.1:#PORT#"
# No proxy required for localhost:
export NO_PROXY="localhost,127.0.0.1,::1"
export no_proxy="$NO_PROXY"

MITM_CA="$HOME/.mitmproxy/mitmproxy-ca-cert.cer"
GUIX_CA="$GUIX_ENVIRONMENT/etc/ssl/certs/ca-certificates.crt"

[[ -r $MITM_CA && -r $GUIX_CA ]] || {
    echo "Cannot read the mitmproxy or Guix CA certificate." >&2
    return 1
}
CA_BUNDLE="/tmp/guix-jail-ca-bundle.pem"
{
    cat "$GUIX_CA"
    printf '\n'
    cat "$MITM_CA"
    printf '\n'
} >| "$CA_BUNDLE" || return 1

export SSL_CERT_FILE="$CA_BUNDLE"
export REQUESTS_CA_BUNDLE="$CA_BUNDLE"
export CURL_CA_BUNDLE="$CA_BUNDLE"
export GIT_SSL_CAINFO="$CA_BUNDLE"
export NODE_EXTRA_CA_CERTS="$MITM_CA"

# Set environment for API keys
export OPENAI_API_KEY="dummy_key"
export ANTHROPIC_API_KEY="dummy_key"
export OLLAMA_API_KEY="dummy-key"
export LANGSMITH_API_KEY="dummy-key"
export LANGSMITH_TRACING="false"
export LANGSMITH_PROJECT="lca-deepagents"

export GUIX_JAIL_ENV_READY=1
