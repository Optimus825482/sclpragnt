import AppLoader from "./components/AppLoader";

export default function Loading() {
  return (
    <AppLoader
      variant="default"
      label="SAYFA YÜKLENİYOR…"
      sublabel="Scalper Agent v4 arayüzü hazırlanıyor"
      minHeight="min-h-[50vh]"
    />
  );
}

