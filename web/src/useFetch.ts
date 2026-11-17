import { useEffect, useState } from "react";

type State<T> = { status: "loading" } | { status: "error"; message: string } | { status: "ok"; data: T };

/** Run `load` when `key` changes, cancelling the previous request. */
export function useFetch<T>(key: string, load: (signal: AbortSignal) => Promise<T>): State<T> {
  const [state, setState] = useState<State<T>>({ status: "loading" });

  useEffect(() => {
    const controller = new AbortController();
    setState({ status: "loading" });
    load(controller.signal)
      .then((data) => setState({ status: "ok", data }))
      .catch((error: Error) => {
        if (error.name !== "AbortError") setState({ status: "error", message: error.message });
      });
    return () => controller.abort();
    // `load` is recreated every render; `key` is what identifies the request.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key]);

  return state;
}
