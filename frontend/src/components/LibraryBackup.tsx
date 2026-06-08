import { Alert, Button, FileButton, Group, List, ScrollArea, Stack, Text } from "@mantine/core";
import { useState } from "react";
import type { LibraryImportResult } from "../api/types.gen";
import { useDataInvalidators } from "../lib/invalidate";
import { exportLibrary, importLibrary } from "../lib/libraryBackup";

export function LibraryBackup() {
  const invalidate = useDataInvalidators();
  const [exporting, setExporting] = useState(false);
  const [exportError, setExportError] = useState<string | null>(null);
  const [importBusy, setImportBusy] = useState(false);
  const [importError, setImportError] = useState<string | null>(null);
  const [importResult, setImportResult] = useState<LibraryImportResult | null>(null);

  const doExport = async () => {
    setExporting(true);
    setExportError(null);
    try {
      await exportLibrary();
    } catch (err) {
      setExportError(err instanceof Error ? err.message : String(err));
    } finally {
      setExporting(false);
    }
  };

  const doImport = async (file: File | null) => {
    if (!file) return;
    setImportBusy(true);
    setImportError(null);
    setImportResult(null);
    try {
      const result = await importLibrary(file);
      setImportResult(result);
      invalidate.targets();
    } catch (err) {
      setImportError(err instanceof Error ? err.message : String(err));
    } finally {
      setImportBusy(false);
    }
  };

  return (
    <Stack gap="md">
      <Group>
        <Button variant="light" onClick={doExport} loading={exporting}>
          Export library
        </Button>
        <FileButton onChange={doImport} accept=".yaml,.yml,application/yaml,text/yaml,text/plain">
          {(props) => (
            <Button variant="light" loading={importBusy} {...props}>
              Import library…
            </Button>
          )}
        </FileButton>
      </Group>
      {exportError && (
        <Alert color="red" variant="light">
          Export failed: {exportError}
        </Alert>
      )}
      {importError && (
        <Alert color="red" variant="light">
          Import failed: {importError}
        </Alert>
      )}
      {importResult && (
        <Alert
          color={importResult.errors.length > 0 ? "yellow" : "green"}
          variant="light"
          title={`Imported ${importResult.imported}, updated ${importResult.updated}`}
        >
          {importResult.errors.length === 0 ? (
            <Text size="sm">Done.</Text>
          ) : (
            <Stack gap={4}>
              <Text size="sm">{importResult.errors.length} entries had problems:</Text>
              {/* Mirror UpdateLxcCard's ChangelogList: grow with the error count
                  but cap viewport-relative so a 500-line bad import stays a
                  scrollable panel instead of pushing the whole page down. */}
              <ScrollArea.Autosize mah="min(40vh, 320px)" type="auto">
                <List size="sm" withPadding>
                  {importResult.errors.map((e) => (
                    <List.Item key={e}>{e}</List.Item>
                  ))}
                </List>
              </ScrollArea.Autosize>
            </Stack>
          )}
        </Alert>
      )}
    </Stack>
  );
}
