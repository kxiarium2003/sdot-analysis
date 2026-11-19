import Foundation
import PDFKit
// usage: pdfwords <pdf> <out.tsv> ; rows: page \t y(mid, top-origin) \t x0 \t x1 \t h \t word
let args = CommandLine.arguments
guard let doc = PDFDocument(url: URL(fileURLWithPath: args[1])) else { print("open fail"); exit(1) }
var out = "page\ty\tx0\tx1\th\tword\n"
for p in 0..<doc.pageCount {
  guard let page = doc.page(at: p) else { continue }
  let H = page.bounds(for: .mediaBox).height
  var items: [(x0: CGFloat, x1: CGFloat, y: CGFloat, h: CGFloat, c: String)] = []
  let n = page.numberOfCharacters
  for i in 0..<n {
    guard let sel = page.selection(for: NSRange(location: i, length: 1)), let ch = sel.string else { continue }
    let b = sel.bounds(for: page)
    if !ch.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty && b.width > 0 && b.height > 0 {
      if let l = items.last, l.c == ch, abs(l.x0 - b.minX) < 0.5, abs(l.y - (H - b.midY)) < 0.5 { continue }
      items.append((b.minX, b.maxX, H - b.midY, b.height, ch))
    }
  }
  items.sort { $0.y < $1.y }
  var lines: [[(x0: CGFloat, x1: CGFloat, y: CGFloat, h: CGFloat, c: String)]] = []
  for it in items {
    if let last = lines.last, let f = last.first, abs(f.y - it.y) < max(1.5, min(f.h, it.h) * 0.45) { lines[lines.count-1].append(it) } else { lines.append([it]) }
  }
  for ln in lines {
    let sorted = ln.sorted { $0.x0 < $1.x0 }
    var w = ""; var wx0: CGFloat = 0; var wx1: CGFloat = 0; var hh: CGFloat = 0
    let ymid = sorted.map { $0.y }.reduce(0, +) / CGFloat(sorted.count)
    func flush() { if !w.isEmpty { out += "\(p+1)\t\(String(format: "%.1f", ymid))\t\(String(format: "%.1f", wx0))\t\(String(format: "%.1f", wx1))\t\(String(format: "%.1f", hh))\t\(w)\n" }; w = "" }
    for it in sorted {
      if !w.isEmpty && it.x0 - wx1 > max(1.2, it.h * 0.28) { flush() }
      if w.isEmpty { wx0 = it.x0; hh = it.h }
      w += it.c; wx1 = max(wx1, it.x1)
      if w.count == 1 { wx1 = it.x1 }
    }
    flush()
  }
}
try! out.write(toFile: args[2], atomically: true, encoding: .utf8)
