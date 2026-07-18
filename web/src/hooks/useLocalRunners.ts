import { useQuery } from "@tanstack/react-query";
import { fetchLocalRunners, type LocalRunnerSummary } from "@/lib/remoteRunner";

export function useLocalRunners(enabled: boolean) {
  return useQuery<LocalRunnerSummary[]>({
    queryKey: ["local-runners"],
    queryFn: fetchLocalRunners,
    enabled,
    staleTime: 10_000,
    refetchInterval: enabled ? 10_000 : false,
  });
}
