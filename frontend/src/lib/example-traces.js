/**
 * Real example addresses, offered as one-click starting points.
 *
 * WHY THESE EXIST
 *
 * The trace console asks for a wallet address, and the person most likely to be
 * reading it at that moment does not have one. An investigator arrives with a
 * victim's address from a complaint. An evaluator arrives with nothing, and the
 * instruction "paste an address" is correct and unusable, because producing a
 * valid address is crypto literacy work that has to happen before the product
 * gets to show anything. So the console offers a few addresses that are already
 * public, already verifiable, and already produce an interesting trace.
 *
 * WHY EVERY ONE OF THEM IS A TOKEN CONTRACT
 *
 * These are token contracts, not wallets. That is a deliberate constraint, not a
 * convenience. A risk score sitting next to an address reads as an accusation
 * about whoever owns that address, and this is a fraud-attribution tool: the
 * address it traces is by definition sometimes a victim's and sometimes a
 * suspect's. Tracing a stranger's personal wallet as the product's front-page
 * example would put an unlabelled member of the public next to a CRITICAL badge
 * on an evaluator's screen, for no benefit a token contract does not also
 * provide. A token contract cannot be defamed by a risk score, because nobody
 * thinks Tether is a scammer.
 *
 * That constraint has teeth, and applying it honestly changed the list. An
 * address originally included here was dropped after checking: it was a
 * perfectly good address that produced a good trace, but nothing in the data
 * identified its owner, and "I could not establish whose it is" is exactly the
 * test that excludes an address from a public demo.
 *
 * EVERY CLAIM BELOW WAS CHECKED AGAINST THE LIVE SYSTEM
 *
 * Each `shows` string describes what an actual trace returned, not what the
 * product ought to be able to do. If a provider stops labelling these addresses,
 * the caption stops being true, and it should be corrected rather than left to
 * imply a capability that is no longer there.
 */

export const EXAMPLE_TRACES = [
  {
    address: "TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t",
    chain: "tron",
    label: "USDT on TRON",
    shows:
      "Exchange identification. Tracing the TRC-20 USDT contract surfaces a counterparty labelled Bybit, type exchange, from a public provider at 70% confidence.",
    caveat:
      "The score is driven by the wallets around USDT, not by USDT. A token contract's own fan-in and fan-out are not computed, because a contract consolidating transfers is the contract working.",
  },
  {
    address: "0xdAC17F958D2ee523a2206206994597C13D831ec7",
    chain: "ethereum",
    label: "USDT on Ethereum",
    shows:
      "The same asset on a second network, resolved independently, and the token-identity check at work: contracts that self-report the symbol 'USDT' are shown as unverified rather than mistaken for Tether.",
    caveat:
      "Expect to see amounts labelled 'UNVERIFIED (claims USDT)'. Those are real transfers of contracts that lie about what they are, and their amounts are denominated in an asset of unknown value.",
  },
  {
    address: "0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2",
    chain: "ethereum",
    label: "WETH on Ethereum",
    shows:
      "A dense, fast graph. WETH is touched by many addresses per block, so this fills the fund-flow view quickly and resolves the contract to WETH9.",
    caveat:
      "Takes longer than the others, and the graph is busy. There is a great deal of real activity to retrieve, and none of it is being hidden.",
  },
];

/**
 * Shorten an address for display without making it ambiguous.
 *
 * Both ends are kept. An address shown only at the tail is indistinguishable
 * from every other address sharing its first four characters, and this is a
 * tool whose entire value is that a reader can go and check an address on an
 * explorer themselves.
 */
export function shortAddress(value, lead = 8, tail = 6) {
  const text = String(value || "");
  if (text.length <= lead + tail + 1) return text;
  return `${text.slice(0, lead)}…${text.slice(-tail)}`;
}
