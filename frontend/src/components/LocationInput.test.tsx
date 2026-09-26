import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { expect, test, vi } from "vitest";

import { api } from "../api";
import LocationInput from "./LocationInput";

vi.mock("../api", () => ({
  api: {
    geocodeSuggestions: vi.fn(),
    geocodeDetails: vi.fn(),
  },
}));

test("requires a selected geocoding suggestion before the location is valid", async () => {
  const mockedApi = vi.mocked(api);
  mockedApi.geocodeSuggestions.mockResolvedValue([
    {
      place_id: "goong:1",
      description: "Quận 1, TP.HCM",
      main_text: "Quận 1",
      secondary_text: "TP.HCM",
      provider: "goong",
    },
  ]);
  mockedApi.geocodeDetails.mockResolvedValue({
    place_id: "goong:1",
    label: "Quận 1, TP.HCM",
    location: { lat: 10.7769, lon: 106.7009, label: "Quận 1, TP.HCM" },
    provider: "goong",
  });
  const onSelect = vi.fn();
  const onValidityChange = vi.fn();

  render(
    <LocationInput
      label="Điểm đi"
      point={{ lat: 10.7, lon: 106.7, label: "Điểm demo" }}
      onSelect={onSelect}
      onValidityChange={onValidityChange}
    />,
  );
  fireEvent.change(screen.getByRole("textbox", { name: "Điểm đi" }), {
    target: { value: "Quận 1" },
  });

  expect(onValidityChange).toHaveBeenLastCalledWith(false);
  fireEvent.click(await screen.findByRole("button", { name: /Quận 1/i }));
  await waitFor(() => expect(onSelect).toHaveBeenCalled());
  expect(onValidityChange).toHaveBeenLastCalledWith(true);
});
