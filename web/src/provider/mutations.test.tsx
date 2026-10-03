import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { describe, expect, it, vi } from "vitest";
import { ApiError } from "../api/client";
import { queryKeys } from "../api/queries";
import { pKeys, useProviderMutation } from "./api";

function setup(userId: string) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  qc.setQueryData(queryKeys.me, { user_id: userId });
  const wrapper = ({ children }: { children: ReactNode }) => <QueryClientProvider client={qc}>{children}</QueryClientProvider>;
  let finish: (v: { name: string }) => void = () => undefined;
  const reply = new Promise<{ name: string }>((resolve) => (finish = resolve));
  const onSuccess = vi.fn((profile: { name: string }) => qc.setQueryData(pKeys.profile, profile));
  const sent = vi.fn(() => reply); // the request, on its way
  const hook = renderHook(() => useProviderMutation({ mutationFn: sent, onSuccess }), { wrapper });
  return { qc, hook, onSuccess, sent, finish: (v: { name: string }) => finish(v) };
}

describe("a provider-app mutation", () => {
  it("drops a reply that arrives after someone else signed in: nothing written, nothing called", async () => {
    const { qc, hook, onSuccess, sent, finish } = setup("dave");
    const caller = vi.fn();
    act(() => hook.result.current.mutate(undefined, { onSuccess: caller }));
    await waitFor(() => expect(sent).toHaveBeenCalled());
    qc.setQueryData(queryKeys.me, { user_id: "mike" }); // a magic link signs Mike in meanwhile
    qc.setQueryData(pKeys.profile, { name: "Mike Reynolds" });
    await act(async () => finish({ name: "Dave Hughes" }));
    await waitFor(() => expect(hook.result.current.isError).toBe(true));
    expect(hook.result.current.error).toBeInstanceOf(ApiError);
    expect((hook.result.current.error as ApiError).code).toBe("signed_in_as_someone_else");
    expect(onSuccess).not.toHaveBeenCalled();
    expect(caller).not.toHaveBeenCalled();
    expect(qc.getQueryData(pKeys.profile)).toEqual({ name: "Mike Reynolds" });
  });

  it("writes its reply as usual while the same person is signed in", async () => {
    const { qc, hook, onSuccess, finish } = setup("dave");
    act(() => hook.result.current.mutate());
    await act(async () => finish({ name: "Dave Hughes" }));
    await waitFor(() => expect(hook.result.current.isSuccess).toBe(true));
    expect(onSuccess).toHaveBeenCalledOnce();
    expect(qc.getQueryData(pKeys.profile)).toEqual({ name: "Dave Hughes" });
  });
});
