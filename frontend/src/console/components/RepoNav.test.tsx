import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import RepoNav from "./RepoNav";
import {
  linkToCoverage,
  linkToDocuments,
  linkToHealth,
  linkToMapping,
  linkToRepo,
} from "../routing";

/** Render RepoNav at a controlled path so we can assert the active tab. */
function renderAt(repoId: string, path: string) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <RepoNav repoId={repoId} />
    </MemoryRouter>,
  );
}

describe("RepoNav", () => {
  const repoId = "demo-taskflow";

  it("renders all five tabs with the routing helpers' hrefs", () => {
    renderAt(repoId, linkToRepo(repoId));

    expect(screen.getByRole("link", { name: "Drift" })).toHaveAttribute(
      "href",
      linkToRepo(repoId),
    );
    expect(screen.getByRole("link", { name: "Mapping" })).toHaveAttribute(
      "href",
      linkToMapping(repoId),
    );
    expect(screen.getByRole("link", { name: "Documents" })).toHaveAttribute(
      "href",
      linkToDocuments(repoId),
    );
    expect(screen.getByRole("link", { name: "Coverage" })).toHaveAttribute(
      "href",
      linkToCoverage(repoId),
    );
    expect(screen.getByRole("link", { name: "Health" })).toHaveAttribute(
      "href",
      linkToHealth(repoId),
    );
  });

  it("orders Mapping right after Drift", () => {
    renderAt(repoId, linkToRepo(repoId));
    const labels = screen
      .getAllByRole("link")
      .map((a) => a.textContent);
    expect(labels).toEqual([
      "Drift",
      "Mapping",
      "Documents",
      "Coverage",
      "Health",
    ]);
  });

  it("is wrapped in a labelled nav landmark", () => {
    renderAt(repoId, linkToRepo(repoId));
    expect(
      screen.getByRole("navigation", { name: /repo views/i }),
    ).toBeInTheDocument();
  });

  it("encodes a slashed repo id the same way the helpers do", () => {
    const slashed = "acme/widget";
    renderAt(slashed, linkToMapping(slashed));
    expect(screen.getByRole("link", { name: "Mapping" })).toHaveAttribute(
      "href",
      linkToMapping(slashed),
    );
    // The helper preserves the slash (encodes each segment), so it survives.
    expect(linkToMapping(slashed)).toBe("/repos/acme/widget/mapping");
  });

  it("marks Drift active on the base /repos/:id path (no suffix)", () => {
    renderAt(repoId, linkToRepo(repoId));
    expect(screen.getByRole("link", { name: "Drift" })).toHaveAttribute(
      "aria-current",
      "page",
    );
    expect(
      screen.getByRole("link", { name: "Mapping" }),
    ).not.toHaveAttribute("aria-current");
  });

  it("marks Mapping active on the /mapping suffix", () => {
    renderAt(repoId, linkToMapping(repoId));
    expect(screen.getByRole("link", { name: "Mapping" })).toHaveAttribute(
      "aria-current",
      "page",
    );
    expect(screen.getByRole("link", { name: "Drift" })).not.toHaveAttribute(
      "aria-current",
    );
  });

  it("marks Documents active on the /documents suffix", () => {
    renderAt(repoId, linkToDocuments(repoId));
    expect(screen.getByRole("link", { name: "Documents" })).toHaveAttribute(
      "aria-current",
      "page",
    );
  });

  it("marks Coverage active on the /coverage suffix", () => {
    renderAt(repoId, linkToCoverage(repoId));
    expect(screen.getByRole("link", { name: "Coverage" })).toHaveAttribute(
      "aria-current",
      "page",
    );
  });

  it("marks Health active on the /health suffix", () => {
    renderAt(repoId, linkToHealth(repoId));
    expect(screen.getByRole("link", { name: "Health" })).toHaveAttribute(
      "aria-current",
      "page",
    );
  });
});
