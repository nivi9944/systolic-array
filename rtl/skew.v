// -----------------------------------------------------------------------------
// skew.v : triangular input skew
//
// Lane i of the input bus is delayed by i clock cycles (lane 0 passes straight
// through). Used once for the rows of A and once for the columns of B so that
// A[i][k] and B[k][j] reach PE(i,j) in the same cycle.
//
//   lane 0 : ----------------------->
//   lane 1 : --[R]------------------>
//   lane 2 : --[R]--[R]------------->
//   lane N-1: --[R]--[R]-- ... --[R]->   (N-1 registers)
// -----------------------------------------------------------------------------
module skew #(
    parameter N      = 8,
    parameter DATA_W = 8
) (
    input  wire                  clk,
    input  wire                  rst_n,
    input  wire [N*DATA_W-1:0]   din,
    output wire [N*DATA_W-1:0]   dout
);

    genvar i;
    generate
        for (i = 0; i < N; i = i + 1) begin : g_lane
            if (i == 0) begin : g_pass
                assign dout[DATA_W-1:0] = din[DATA_W-1:0];
            end else begin : g_delay
                // i-stage shift register, flattened: stage d at [d*DATA_W +: DATA_W]
                // Shifting left by DATA_W moves every stage one step along.
                reg [i*DATA_W-1:0] sr;
                if (i == 1) begin : g_one
                    always @(posedge clk or negedge rst_n) begin
                        if (!rst_n) sr <= {DATA_W{1'b0}};
                        else        sr <= din[i*DATA_W +: DATA_W];
                    end
                end else begin : g_many
                    always @(posedge clk or negedge rst_n) begin
                        if (!rst_n) sr <= {(i*DATA_W){1'b0}};
                        else        sr <= {sr[(i-1)*DATA_W-1:0], din[i*DATA_W +: DATA_W]};
                    end
                end
                assign dout[i*DATA_W +: DATA_W] = sr[(i-1)*DATA_W +: DATA_W];
            end
        end
    endgenerate

endmodule
