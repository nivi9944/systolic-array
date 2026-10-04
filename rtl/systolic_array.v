// -----------------------------------------------------------------------------
// systolic_array.v : N x N grid of output-stationary PEs
//
//            b_col[0]  b_col[1]  ...  b_col[N-1]      (already skewed)
//               |         |               |
//   a_row[0] -> PE00 ---> PE01 ---> ... -> PE0,N-1   -> acc_top (row 0 results)
//               |         |               |
//   a_row[1] -> PE10 ---> PE11 ---> ... -> PE1,N-1
//               ...
//   a_row[N-1]->PEN-1,0 -> ...           -> PEN-1,N-1
//
// A values move right, B values move down, every PE(i,j) accumulates C[i][j].
// In drain mode (shift = 1) the accumulators move up one row per cycle, so the
// top row presents C row 0, then row 1, and so on.
// -----------------------------------------------------------------------------
module systolic_array #(
    parameter N      = 8,
    parameter DATA_W = 8,
    parameter ACC_W  = 32,
    parameter PIPE   = 1,
    parameter ISO    = 1
) (
    input  wire                  clk,
    input  wire                  rst_n,
    input  wire                  shift,
    input  wire [N*DATA_W-1:0]   a_row,     // lane i feeds row i (from the left)
    input  wire [N*DATA_W-1:0]   b_col,     // lane j feeds column j (from the top)
    output wire [N*ACC_W-1:0]    acc_top    // accumulators of row 0, lane j = column j
);

    // Links between neighbouring PEs, kept as arrays of small wires (one per PE
    // port) rather than one wide flat bus: simulators and synthesis handle this
    // far better than thousands of part-selects on a single net.
    //   a_link[i*(N+1)+j] : A value entering PE(i,j) from the left (j = N: unused)
    //   b_link[i*N+j]     : B value entering PE(i,j) from the top  (i = N: unused)
    //   acc_link[i*N+j]   : accumulator of PE(i,j); row N is a zero row that is
    //                       shifted into the bottom PEs during drain
    // The a_out of the last column and b_out of the last row leave the grid
    // unused (synthesis removes those registers), so silence that lint note.
    /* verilator lint_off UNUSEDSIGNAL */
    wire [DATA_W-1:0] a_link   [0:N*(N+1)-1];
    wire [DATA_W-1:0] b_link   [0:(N+1)*N-1];
    /* verilator lint_on UNUSEDSIGNAL */
    wire [ACC_W-1:0]  acc_link [0:(N+1)*N-1];

    genvar i, j;
    generate
        for (i = 0; i < N; i = i + 1) begin : g_row_in
            assign a_link[i*(N+1)] = a_row[i*DATA_W +: DATA_W];
        end
        for (j = 0; j < N; j = j + 1) begin : g_col_in
            assign b_link[j]                 = b_col[j*DATA_W +: DATA_W];
            assign acc_link[N*N+j]           = {ACC_W{1'b0}};
            assign acc_top[j*ACC_W +: ACC_W] = acc_link[j];
        end

        for (i = 0; i < N; i = i + 1) begin : g_row
            for (j = 0; j < N; j = j + 1) begin : g_col
                pe #(
                    .DATA_W (DATA_W),
                    .ACC_W  (ACC_W),
                    .PIPE   (PIPE),
                    .ISO    (ISO)
                ) u_pe (
                    .clk    (clk),
                    .rst_n  (rst_n),
                    .shift  (shift),
                    .a_in   (a_link[i*(N+1)+j]),
                    .b_in   (b_link[i*N+j]),
                    .acc_in (acc_link[(i+1)*N+j]),
                    .a_out  (a_link[i*(N+1)+j+1]),
                    .b_out  (b_link[(i+1)*N+j]),
                    .acc    (acc_link[i*N+j])
                );
            end
        end
    endgenerate

endmodule
