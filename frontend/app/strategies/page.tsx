import { redirect } from "next/navigation";

export default function StrategiesPage() {
  redirect("/settings?tab=strategies");
}
