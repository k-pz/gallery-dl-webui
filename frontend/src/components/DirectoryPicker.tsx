import {
  ActionIcon,
  Button,
  Group,
  Loader,
  Paper,
  Select,
  Stack,
  Text,
  TextInput,
  Tooltip,
} from "@mantine/core";
import { useMutation, useQuery } from "@tanstack/react-query";
import { useMemo, useState } from "react";
import { createOutputDirMutation, listOutputDirsOptions } from "../api/@tanstack/react-query.gen";
import { extractErrorMessage } from "../lib/apiError";
import { useDataInvalidators } from "../lib/invalidate";

export interface DirectoryPickerProps {
  label: string;
  description?: string;
  placeholder?: string;
  value: string | null;
  onChange: (value: string | null) => void;
  /** When true, the input + Select are read-only. */
  disabled?: boolean;
  /** True when a postprocess_root is set. When false, the picker just renders disabled. */
  enabled: boolean;
  /** Extra path that should appear in the dropdown even if it's not in the listing. */
  extraOption?: string | null;
}

export function DirectoryPicker({
  label,
  description,
  placeholder,
  value,
  onChange,
  disabled,
  enabled,
  extraOption,
}: DirectoryPickerProps) {
  const invalidate = useDataInvalidators();
  const { data, isLoading } = useQuery({
    ...listOutputDirsOptions(),
    enabled,
  });

  const [showCreate, setShowCreate] = useState(false);
  const [createPath, setCreatePath] = useState("");
  const [createError, setCreateError] = useState<string | null>(null);

  const options = useMemo(() => {
    const set = new Set<string>();
    const paths: string[] = [];
    const push = (p: string | null | undefined) => {
      if (!p) return;
      if (set.has(p)) return;
      set.add(p);
      paths.push(p);
    };
    push(value);
    push(extraOption ?? null);
    if (Array.isArray(data)) for (const d of data) push(d.path);
    return paths.map((p) => ({ value: p, label: p }));
  }, [data, extraOption, value]);

  const create = useMutation({
    ...createOutputDirMutation(),
    onSuccess: (entry) => {
      setCreateError(null);
      setShowCreate(false);
      setCreatePath("");
      onChange(entry.path);
      invalidate.outputDirs();
    },
    onError: (err) => setCreateError(extractErrorMessage(err)),
  });

  const submitCreate = () => {
    const trimmed = createPath.trim();
    if (!trimmed) {
      setCreateError("path is required");
      return;
    }
    setCreateError(null);
    create.mutate({ body: { path: trimmed } });
  };

  return (
    <Stack gap="xs">
      <Group align="flex-end" gap="xs" wrap="nowrap">
        <Select
          style={{ flex: 1, fontFamily: "var(--app-mono)" }}
          label={label}
          description={description}
          placeholder={placeholder ?? "Pick a folder"}
          data={options}
          value={value || null}
          onChange={(v) => onChange(v)}
          searchable
          clearable
          nothingFoundMessage={isLoading ? "Loading…" : "No folders found"}
          disabled={disabled || !enabled}
          comboboxProps={{ withinPortal: true }}
          rightSection={isLoading ? <Loader size="xs" /> : undefined}
        />
        <Tooltip label={showCreate ? "Cancel" : "Create folder"} withArrow>
          <ActionIcon
            variant="default"
            size="lg"
            disabled={disabled || !enabled}
            onClick={() => setShowCreate((s) => !s)}
            aria-label="Create folder"
          >
            {showCreate ? "×" : "+"}
          </ActionIcon>
        </Tooltip>
      </Group>
      {showCreate && (
        <Paper
          withBorder
          p="md"
          radius="md"
          style={{ backgroundColor: "var(--app-surface-muted)" }}
        >
          <Stack gap="xs">
            <Group align="flex-end" gap="xs" wrap="wrap">
              <TextInput
                style={{ flex: 1, minWidth: 200 }}
                label="New folder name"
                description="A single folder under the root — no slashes."
                placeholder="manga"
                value={createPath}
                onChange={(e) => setCreatePath(e.currentTarget.value)}
                disabled={create.isPending}
                onKeyDown={(e) => {
                  if (e.key === "Enter") submitCreate();
                }}
              />
              <Button onClick={submitCreate} loading={create.isPending} style={{ flexGrow: 1 }}>
                Create
              </Button>
              <Button
                variant="subtle"
                color="gray"
                onClick={() => {
                  setShowCreate(false);
                  setCreateError(null);
                  setCreatePath("");
                }}
                disabled={create.isPending}
              >
                Cancel
              </Button>
            </Group>
            {createError && (
              <Text size="sm" c="red">
                {createError}
              </Text>
            )}
          </Stack>
        </Paper>
      )}
    </Stack>
  );
}
