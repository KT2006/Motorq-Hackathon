const inrFormatter = (maximumFractionDigits) =>
  new Intl.NumberFormat('en-IN', {
    style: 'currency',
    currency: 'INR',
    maximumFractionDigits,
  });

export function formatINR(value, maximumFractionDigits = 0) {
  const amount = Number(value);
  return inrFormatter(maximumFractionDigits).format(Number.isFinite(amount) ? amount : 0);
}
