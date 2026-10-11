import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";

import { api } from "../api";
import LocationInput from "./LocationInput";

vi.mock("../api", () => ({
  api: {
    geocodeSuggestions: vi.fn(),
    geocodeDetails: vi.fn(),
    reverseGeocode: vi.fn(),
  },
}));

function stubGeolocation(result: { latitude: number; longitude: number } | { code: number }) {
  Object.defineProperty(navigator, "geolocation", {
    configurable: true,
    value: {
      getCurrentPosition: (ok: (position: unknown) => void, fail: (error: unknown) => void) => {
        if ("code" in result) fail({ code: result.code });
        else ok({ coords: result });
      },
    },
  });
}

afterEach(() => {
  vi.mocked(api).reverseGeocode.mockReset();
  Reflect.deleteProperty(navigator, "geolocation");
});

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

const here = { lat: 10.7075, lon: 106.705, label: "Điểm demo" };

test("uses the browser location and replaces its label with the reverse-geocoded address", async () => {
  stubGeolocation({ latitude: 10.78, longitude: 106.69 });
  vi.mocked(api).reverseGeocode.mockResolvedValue({
    place_id: "p",
    label: "1 Nguyễn Huệ, Quận 1",
    location: { lat: 10.78, lon: 106.69, label: "1 Nguyễn Huệ, Quận 1" },
    provider: "goong",
  });
  const onSelect = vi.fn();
  const onValidityChange = vi.fn();
  render(<LocationInput label="Điểm đi" point={here} onSelect={onSelect} onValidityChange={onValidityChange} />);

  fireEvent.click(screen.getByRole("button", { name: /vị trí hiện tại/i }));

  await waitFor(() =>
    expect(onSelect).toHaveBeenCalledWith({ lat: 10.78, lon: 106.69, label: "1 Nguyễn Huệ, Quận 1" }),
  );
  expect(onValidityChange).toHaveBeenLastCalledWith(true);
});

test("falls back to a fixed label when reverse geocoding fails", async () => {
  stubGeolocation({ latitude: 10.78, longitude: 106.69 });
  vi.mocked(api).reverseGeocode.mockRejectedValue(new Error("503"));
  const onSelect = vi.fn();
  render(<LocationInput label="Điểm đi" point={here} onSelect={onSelect} onValidityChange={vi.fn()} />);

  fireEvent.click(screen.getByRole("button", { name: /vị trí hiện tại/i }));

  await waitFor(() =>
    expect(onSelect).toHaveBeenCalledWith({ lat: 10.78, lon: 106.69, label: "Vị trí hiện tại" }),
  );
});

test("shows an error and keeps the point when location permission is denied", async () => {
  stubGeolocation({ code: 1 });
  const onSelect = vi.fn();
  render(<LocationInput label="Điểm đi" point={here} onSelect={onSelect} onValidityChange={vi.fn()} />);

  fireEvent.click(screen.getByRole("button", { name: /vị trí hiện tại/i }));

  expect(await screen.findByText(/chưa được cấp quyền vị trí/i)).toBeInTheDocument();
  expect(onSelect).not.toHaveBeenCalled();
});

test("offers picking on the map only when a handler is provided", () => {
  const onPickOnMap = vi.fn();
  const { rerender } = render(
    <LocationInput label="Điểm đi" point={here} onSelect={vi.fn()} onValidityChange={vi.fn()} />,
  );
  expect(screen.queryByRole("button", { name: /trên bản đồ/i })).not.toBeInTheDocument();

  rerender(
    <LocationInput
      label="Điểm đi"
      point={here}
      picking
      onSelect={vi.fn()}
      onValidityChange={vi.fn()}
      onPickOnMap={onPickOnMap}
    />,
  );
  const button = screen.getByRole("button", { name: /trên bản đồ/i });
  expect(button).toHaveAttribute("aria-pressed", "true");
  fireEvent.click(button);
  expect(onPickOnMap).toHaveBeenCalledTimes(1);
});
