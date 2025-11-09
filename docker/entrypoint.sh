#!/usr/bin/env sh
set -e

# Ensure postes.csv exists
[ -f "$POSTES_PATH" ] || { 
  mkdir -p "$(dirname "$POSTES_PATH")"
  echo "GuidString,FinAffichage,tempsRestant,Nopost,Titpost,Nmemp,Lieupost,IsPostulee,IsNouveau,IsFavori,IsInternational,DureePoste,dtcr" > "$POSTES_PATH"
  echo "Initialized empty postes file at $POSTES_PATH"
}

# Check if host pcscd socket is mounted
if [ -S /run/pcscd/pcscd.comm ]; then
  echo "Using host pcscd"
else
  echo "Starting local pcscd (fallback)"
  mkdir -p /run/pcscd
  pcscd --disable-polkit -f &
  for i in $(seq 1 50); do 
    [ -S /run/pcscd/pcscd.comm ] && break
    sleep 0.1
  done
fi

# Ensure data dir exists (redundant safety)
mkdir -p /data

# Launch the actual app
exec "$@"
