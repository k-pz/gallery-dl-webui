import { notifications } from "@mantine/notifications";
import { type UseMutationOptions, useMutation } from "@tanstack/react-query";
import { extractErrorMessage } from "./apiError";

type Resolvable<T, Arg, Vars> = T | ((arg: Arg, vars: Vars) => T);

function resolve<T, Arg, Vars>(value: Resolvable<T, Arg, Vars>, arg: Arg, vars: Vars): T {
  return typeof value === "function" ? (value as (a: Arg, v: Vars) => T)(arg, vars) : value;
}

type SuccessNotice<TData, TVars> = {
  title: Resolvable<string, TData, TVars>;
  message: Resolvable<string, TData, TVars>;
  color?: string;
};

type ErrorNotice<TError, TVars> = {
  title: Resolvable<string, TError, TVars>;
  /** Defaults to `extractErrorMessage(err)`. Override only when the message
   *  should not be derived from the thrown error. */
  message?: Resolvable<string, TError, TVars>;
  color?: string;
};

/**
 * `useMutation` wrapper that fires a Mantine notification on success/error
 * using the existing `extractErrorMessage` helper. The base mutation options
 * (typically a generated `*Mutation()` from `api/@tanstack/react-query.gen`)
 * are spread first; `onSuccess`/`onError` from the base run *after* the
 * notification, so callers can still do their own invalidation and state
 * cleanup.
 */
export function useNotifyingMutation<TData, TError, TVars>(
  base: UseMutationOptions<TData, TError, TVars>,
  notify: {
    success?: SuccessNotice<TData, TVars>;
    error?: ErrorNotice<TError, TVars>;
  },
) {
  const { success, error } = notify;
  return useMutation<TData, TError, TVars>({
    ...base,
    onSuccess: (data, vars, onMutateResult, ctx) => {
      if (success) {
        notifications.show({
          title: resolve(success.title, data, vars),
          message: resolve(success.message, data, vars),
          color: success.color,
        });
      }
      base.onSuccess?.(data, vars, onMutateResult, ctx);
    },
    onError: (err, vars, onMutateResult, ctx) => {
      if (error) {
        notifications.show({
          title: resolve(error.title, err, vars),
          message:
            error.message !== undefined
              ? resolve(error.message, err, vars)
              : extractErrorMessage(err),
          color: error.color ?? "red",
        });
      }
      base.onError?.(err, vars, onMutateResult, ctx);
    },
  });
}
