#!/bin/bash
# CMS Connect-style wrapper: cmsenv a host-OS-matching CMSSW, then exec xrdhover.
# xrdhover only needs libXrdCl.so.6 from that release. Do not trust cmsset's
# SCRAM_ARCH (it is usually el8) and do not cmsrel on the WN.
set -euo pipefail

CMSSW="${CMSSW:-CMSSW_20_1_0_pre2}"
while [ $# -gt 0 ]; do
  case "$1" in
    -C|--cmssw)
      CMSSW="$2"
      shift 2
      ;;
    --)
      shift
      break
      ;;
    *)
      break
      ;;
  esac
done

SANDBOX=$(pwd)
XRDHOVER="${SANDBOX}/xrdhover"
SAVED_PROXY="${X509_USER_PROXY:-}"
SAVED_CERT_DIR="${X509_CERT_DIR:-}"
SAVED_HOME="${HOME:-}"

if [ ! -x "$XRDHOVER" ]; then
  echo "tckestrel: xrdhover is not in the sandbox" >&2
  exit 2
fi
if [ ! -f /cvmfs/cms.cern.ch/cmsset_default.sh ]; then
  echo "tckestrel: /cvmfs/cms.cern.ch/cmsset_default.sh is missing" >&2
  exit 2
fi

cpu=amd64
[ "$(uname -m)" = aarch64 ] && cpu=aarch64
host_os=el8
if [ -r /etc/os-release ]; then
  # shellcheck disable=SC1091
  . /etc/os-release
  case "${VERSION_ID%%.*}" in
    8) host_os=el8 ;;
    9) host_os=el9 ;;
    10) host_os=el10 ;;
  esac
fi

# shellcheck disable=SC1091
source /cvmfs/cms.cern.ch/cmsset_default.sh

# cmsset_default.sh almost always exports an el8 SCRAM_ARCH. Using that on a
# rhel9 glidein cmsenv's el8 CMSSW and then misses libssl.so.1.1.
case "${SCRAM_ARCH:-}" in
  "${host_os}_"*) ;;
  *) unset SCRAM_ARCH ;;
esac

pick_release() {
  local arch="$1"
  local cand
  for cand in \
    "/cvmfs/cms.cern.ch/${arch}/cms/cmssw/${CMSSW}" \
    "/cvmfs/cms.cern.ch/${arch}/cms/cmssw-patch/${CMSSW}"; do
    if [ -d "$cand" ]; then
      printf '%s' "$cand"
      return 0
    fi
  done
  return 1
}

rel=""
if [ -n "${SCRAM_ARCH:-}" ]; then
  rel=$(pick_release "$SCRAM_ARCH" || true)
fi
if [ -z "$rel" ]; then
  for gcc in gcc14 gcc13 gcc12 gcc11; do
    SCRAM_ARCH="${host_os}_${cpu}_${gcc}"
    rel=$(pick_release "$SCRAM_ARCH" || true)
    [ -n "$rel" ] && break
  done
fi
if [ -z "$rel" ]; then
  for cand in /cvmfs/cms.cern.ch/"${host_os}"_"${cpu}"_*/cms/cmssw/"${CMSSW}" \
    /cvmfs/cms.cern.ch/"${host_os}"_"${cpu}"_*/cms/cmssw-patch/"${CMSSW}"; do
    if [ -d "$cand" ]; then
      rel=$cand
      SCRAM_ARCH=$(echo "$cand" | awk -F/ '{print $4}')
      break
    fi
  done
fi

if [ -z "$rel" ]; then
  echo "tckestrel: ${CMSSW} not on CVMFS for host ${host_os}_${cpu}" >&2
  echo "tckestrel: do not cmsrel on the WN; pick a release that exists for this OS" >&2
  ls -d /cvmfs/cms.cern.ch/"${host_os}"_"${cpu}"_*/cms/cmssw/"${CMSSW}" \
    /cvmfs/cms.cern.ch/"${host_os}"_"${cpu}"_*/cms/cmssw-patch/"${CMSSW}" \
    2>/dev/null | head >&2 || true
  exit 2
fi

export SCRAM_ARCH
echo "tckestrel: cmsenv ${rel} (SCRAM_ARCH=${SCRAM_ARCH} host=${host_os} cpu=${cpu})" >&2
cd "$rel"
eval "$(scramv1 runtime -sh)"
cd "$SANDBOX"

# cmsenv overwrites grid env and can point TMPDIR at a dead glidein path.
if [ -n "$SAVED_PROXY" ] && [ -f "$SAVED_PROXY" ]; then
  export X509_USER_PROXY="$SAVED_PROXY"
fi
if [ -n "$SAVED_CERT_DIR" ] && [ -d "$SAVED_CERT_DIR" ]; then
  export X509_CERT_DIR="$SAVED_CERT_DIR"
elif [ -d /cvmfs/cms.cern.ch/grid/etc/grid-security/certificates ]; then
  export X509_CERT_DIR=/cvmfs/cms.cern.ch/grid/etc/grid-security/certificates
fi
if [ -z "${HOME:-}" ] || [ ! -w "${HOME:-/}" ]; then
  export HOME="$SANDBOX"
fi
if [ -z "${TMPDIR:-}" ] || [ ! -w "${TMPDIR}" ]; then
  export TMPDIR="$SANDBOX"
fi
# Host /lib64 is a fallback only. Prepending it hid gcc's libstdc++ and broke
# CMSSW libXrdCl.so.6 (GLIBCXX_3.4.3x / CXXABI_1.3.15). scram's path stays first.
if [ -n "${LD_LIBRARY_PATH:-}" ]; then
  export LD_LIBRARY_PATH="${LD_LIBRARY_PATH}:/lib64:/usr/lib64"
else
  export LD_LIBRARY_PATH="/lib64:/usr/lib64"
fi

if command -v ldd >/dev/null 2>&1; then
  echo "tckestrel: ldd xrdhover" >&2
  ldd "$XRDHOVER" >&2 || true
  if ldd "$XRDHOVER" 2>/dev/null | grep -q "not found"; then
    echo "tckestrel: xrdhover has unresolved libraries (exit 2)" >&2
    exit 2
  fi
fi

exec "$XRDHOVER" "$@"
